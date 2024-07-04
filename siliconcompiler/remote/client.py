# Copyright 2020 Silicon Compiler Authors. All Rights Reserved.

import json
import os
import requests
import shutil
import time
import urllib.parse
import tarfile
import tempfile
import multiprocessing

from siliconcompiler import utils, SiliconCompilerError
from siliconcompiler._metadata import default_server
from siliconcompiler.schema import Schema
from siliconcompiler.utils import default_credentials_file
from siliconcompiler.scheduler import _setup_node, _runtask, _executenode
from siliconcompiler.flowgraph import _get_flowgraph_entry_nodes, _get_flowgraph_node_outputs, \
    nodes_to_execute

# Step name to use while logging
remote_step_name = 'remote'

# Client / server timeout
__timeout = 10

# Generate warning if no server is configured
__warn_if_no_server = True

# Multiprocessing interface.
multiprocessor = multiprocessing.get_context('spawn')

__tos_str = '''Please review the SiliconCompiler cloud beta's terms of service:

https://www.siliconcompiler.com/terms-of-service

In particular, please ensure that you have the right to distribute any IP
which is contained in designs that you upload to the service. This public
service, provided by SiliconCompiler, is not intended to process proprietary IP.
'''


###################################
def get_base_url(chip):
    '''Helper method to get the root URL for API calls, given a Chip object.
    '''

    rcfg = get_remote_config(chip, False)
    remote_host = rcfg['address']
    if 'port' in rcfg:
        remote_port = rcfg['port']
    else:
        remote_port = 443
    remote_host += ':' + str(remote_port)
    if remote_host.startswith('http'):
        remote_protocol = ''
    else:
        remote_protocol = 'https://' if str(remote_port) == '443' else 'http://'
    return remote_protocol + remote_host


###################################
def __post(chip, url, post_action, success_action, error_action=None):
    '''
    Helper function to handle the post request
    '''
    redirect_url = urllib.parse.urljoin(get_base_url(chip), url)

    timeouts = 0
    while redirect_url:
        try:
            resp = post_action(redirect_url)
        except requests.Timeout:
            timeouts += 1
            if timeouts > 10:
                raise SiliconCompilerError('Server communications timed out', chip=chip)
            time.sleep(10)
            continue
        except Exception as e:
            raise SiliconCompilerError(f'Server communications error: {e}', chip=chip)

        code = resp.status_code
        if 200 <= code and code < 300:
            return success_action(resp)

        try:
            msg_json = resp.json()
            if 'message' in msg_json:
                msg = msg_json['message']
            else:
                msg = resp.text
        except requests.JSONDecodeError:
            msg = resp.text

        if 300 <= code and code < 400:
            if 'Location' in resp.headers:
                redirect_url = resp.headers['Location']
                continue

        if error_action:
            return error_action(code, msg)
        else:
            raise SiliconCompilerError(f'Server responded with {code}: {msg}', chip=chip)


###################################
def __build_post_params(chip, verbose, job_name=None, job_hash=None):
    '''
    Helper function to build the params for the post request
    '''
    # Use authentication if necessary.
    post_params = {}

    if job_hash:
        post_params['job_hash'] = job_hash

    if job_name:
        post_params['job_id'] = job_name

    rcfg = get_remote_config(chip, verbose)

    if ('username' in rcfg) and ('password' in rcfg) and \
       (rcfg['username']) and (rcfg['password']):
        post_params['username'] = rcfg['username']
        post_params['key'] = rcfg['password']

    return post_params


###################################
def _remote_preprocess(chip, remote_nodelist):
    '''
    Helper method to run a local import stage for remote jobs.
    '''
    preset_step = chip.get('arg', 'step')
    preset_index = chip.get('arg', 'index')

    # Fetch a list of 'import' steps, and make sure they're all at the start of the flow.
    flow = chip.get('option', 'flow')
    entry_nodes = _get_flowgraph_entry_nodes(chip, flow)
    if any([node not in remote_nodelist for node in entry_nodes]) or (len(remote_nodelist) == 1):
        chip.logger.error('Remote flows must be organized such that the starting task(s) are run '
                          'before all other steps, and at least one other task is included.')
        chip.logger.error('Full nodelist: '
                          f'{", ".join([f"{step}{index}" for step, index in remote_nodelist])}')
        chip.logger.error('Starting nodes: '
                          f'{", ".join([f"{step}{index}" for step, index in entry_nodes])}')
        raise SiliconCompilerError('Remote setup invalid', chip=chip)
    # Setup up tools for all local functions
    for local_step, index in entry_nodes:
        tool = chip.get('flowgraph', flow, local_step, index, 'tool')
        # Setting up tool is optional (step may be a builtin function)
        if tool != 'builtin':
            _setup_node(chip, local_step, index)

        # Need to set step/index to only run this node locally
        chip.set('arg', 'step', local_step)
        chip.set('arg', 'index', index)

        if not chip.get('option', 'resume'):

            # Run the actual import step locally with multiprocess as _runtask must
            # be run in a separate thread.
            # We can pass in an empty 'status' dictionary, since _runtask() will
            # only look up a step's dependencies in this dictionary, and the first
            # step should have none.
            run_task = multiprocessor.Process(target=_runtask,
                                              args=(chip,
                                                    flow,
                                                    local_step,
                                                    index,
                                                    {},
                                                    _executenode))
            run_task.start()
            run_task.join()
            if run_task.exitcode != 0:
                # A 'None' or nonzero value indicates that the Process target failed.
                ftask = f'{local_step}{index}'
                raise SiliconCompilerError(
                    f"Could not start remote job: local setup task {ftask} failed.",
                    chip=chip)

    # Ensure packages with python sources are copied
    for key in chip.allkeys():
        key_type = chip.get(*key, field='type')

        if 'dir' in key_type or 'file' in key_type:
            for _, step, index in chip.schema._getvals(*key, return_defvalue=False):
                packages = chip.get(*key, field='package', step=step, index=index)
                force_copy = False
                for package in packages:
                    if not package:
                        continue
                    if package.startswith('python://'):
                        force_copy = True
                if force_copy:
                    chip.set(*key, True, field='copy', step=step, index=index)

    # Collect inputs into a collection directory only for remote runs, since
    # we need to send inputs up to the server.
    chip.collect()

    # This is necessary because the public version of the server somehow loses the information
    # that the entry nodes were already executed
    entry_nodes_successors = set()
    for node in entry_nodes:
        entry_nodes_successors.update(_get_flowgraph_node_outputs(chip, flow, node))
    entry_steps_successors = list(map(lambda node: node[0], entry_nodes_successors))
    chip.set('option', 'from', entry_steps_successors)
    # Recover step/index
    chip.set('arg', 'step', preset_step)
    chip.set('arg', 'index', preset_index)


###################################
def _log_truncated_stats(chip, status, nodes_with_status, nodes_to_print):
    '''
    Helper method to log truncated information about flowgraph nodes
    with a given status, on a single line.
    Used to print info about all statuses besides 'running'.
    '''

    num_nodes = len(nodes_with_status)
    if num_nodes > 0:
        nodes_log = f'  {status.title()} ({num_nodes}): '
        log_nodes = []
        for i in range(min(nodes_to_print, num_nodes)):
            log_nodes.append(nodes_with_status[i][0])
        if num_nodes > nodes_to_print:
            log_nodes.append('...')
        nodes_log += ', '.join(log_nodes)
        chip.logger.info(nodes_log)


###################################
def _process_progress_info(chip, progress_info, nodes_to_print=3):
    '''
    Helper method to log information about a remote run's progress,
    based on information returned from a 'check_progress/' call.
    '''

    completed = []
    try:
        # Decode response JSON, if possible.
        job_info = json.loads(progress_info['message'])
        # Retrieve total elapsed time, if included in the response.
        total_elapsed = ''
        if 'elapsed_time' in job_info:
            total_elapsed = f' (runtime: {job_info["elapsed_time"]})'

        # Sort and store info about the job's progress.
        chip.logger.info(f"Job is still running{total_elapsed}. Status:")
        nodes_to_log = {'completed': [], 'failed': [], 'timeout': [],
                        'running': [], 'queued': [], 'pending': []}
        for node, node_info in job_info.items():
            status = node_info['status']
            nodes_to_log[status].append((node, node_info))
            if (status == 'completed'):
                completed.append(node)

        # Log information about the job's progress.
        # To avoid clutter, only log up to N completed/pending nodes, on a single line.
        # Completed, failed, and timed-out flowgraph nodes:
        for stat in ['completed', 'failed', 'timeout']:
            _log_truncated_stats(chip, stat, nodes_to_log[stat], nodes_to_print)
        # Running / in-progress flowgraph nodes should all be printed:
        num_running = len(nodes_to_log['running'])
        if num_running > 0:
            chip.logger.info(f'  Running ({num_running}):')
            for node_tuple in nodes_to_log['running']:
                node = node_tuple[0]
                node_info = node_tuple[1]
                running_log = f"    {node}"
                if 'elapsed_time' in node_info:
                    running_log += f" ({node_info['elapsed_time']})"
                chip.logger.info(running_log)
        # Queued and pending flowgraph nodes:
        for stat in ['queued', 'pending']:
            _log_truncated_stats(chip, stat, nodes_to_log[stat], nodes_to_print)
    except json.JSONDecodeError:
        # TODO: Remove fallback once all servers are updated to return JSON.
        if (':' in progress_info['message']):
            msg_lines = progress_info['message'].splitlines()
            cur_step = msg_lines[0][msg_lines[0].find(': ') + 2:]
            cur_log = msg_lines[1:]
            chip.logger.info(f"Job is still running (step: {cur_step}).")
            if cur_log:
                chip.logger.info('Tail of current logfile:')
                for line in cur_log:
                    chip.logger.info(line)
        else:
            chip.logger.info("Job is still running (step: unknown)")

    return completed


def get_remote_config(chip, verbose):
    '''
    Returns the remote credentials
    '''
    if chip.get('option', 'credentials'):
        # Use the provided remote credentials file.
        cfg_file = os.path.abspath(chip.get('option', 'credentials'))

        if not os.path.isfile(cfg_file):
            # Check if it's a file since its been requested by the user
            raise SiliconCompilerError(
                f'Unable to find the credentials file: {cfg_file}',
                chip=chip)
    else:
        # Use the default config file path.
        cfg_file = utils.default_credentials_file()

    remote_cfg = {}
    cfg_dir = os.path.dirname(cfg_file)
    if os.path.isdir(cfg_dir) and os.path.isfile(cfg_file):
        if verbose:
            chip.logger.info(f'Using credentials: {cfg_file}')
        with open(cfg_file, 'r') as cfgf:
            remote_cfg = json.loads(cfgf.read())
    else:
        global __warn_if_no_server
        if __warn_if_no_server:
            if verbose:
                chip.logger.warning('Could not find remote server configuration: '
                                    f'defaulting to {default_server}')
            __warn_if_no_server = False
        remote_cfg = {
            "address": default_server
        }
    if 'address' not in remote_cfg:
        raise SiliconCompilerError(
            'Improperly formatted remote server configuration - '
            'please run "sc-remote -configure" and enter your server address and '
            'credentials.', chip=chip)

    return remote_cfg


def remote_process(chip):
    '''
    Dispatch the Chip to a remote server for processing.
    '''
    should_resume = chip.get('option', 'resume')
    remote_resume = should_resume and chip.get('record', 'remoteid')

    # Pre-process: Run an starting nodes locally, and upload the
    # in-progress build directory to the remote server.
    # Data is encrypted if user / key were specified.
    # run remote process
    if should_resume:
        chip.unset('arg', 'step')
        chip.unset('arg', 'index')
    elif chip.get('arg', 'step'):
        raise SiliconCompilerError('Cannot pass "-step" parameter into remote flow.', chip=chip)
    # Only run the pre-process step if the job doesn't already have a remote ID.
    if not remote_resume:
        _remote_preprocess(chip, nodes_to_execute(chip, chip.get('option', 'flow')))

    # Run the job on the remote server, and wait for it to finish.
    # Set logger to indicate remote run
    chip._init_logger(step=remote_step_name, index=None, in_run=True)
    _remote_run(chip)

    # Restore logger
    chip._init_logger(in_run=True)


###################################
def _remote_run(chip):
    '''
    Helper method to run a job stage on a remote compute cluster.
    Note that files will not be copied to the remote stage; typically
    the source files will be copied into the cluster's storage before
    calling this method.
    If the "-remote" parameter was not passed in, this method
    will print a warning and do nothing.
    This method assumes that the given stage should not be skipped,
    because it is called from within the `Chip.run(...)` method.

    '''

    # Ask the remote server to start processing the requested step.
    check_interval = _request_remote_run(chip)

    # Remove the local 'import.tar.gz' archive.
    local_archive = os.path.join(chip.getworkdir(),
                                 'import.tar.gz')
    if os.path.isfile(local_archive):
        os.remove(local_archive)

    # Run the main 'check_progress' loop to monitor job status until it finishes.
    remote_run_loop(chip, check_interval)


###################################
def remote_run_loop(chip, check_interval):
    # Wrapper to allow for capturing of Ctrl+C
    try:
        __remote_run_loop(chip, check_interval)
    except KeyboardInterrupt:
        entry_step, entry_index = \
            _get_flowgraph_entry_nodes(chip, chip.get('option', 'flow'))[0]
        entry_manifest = os.path.join(chip.getworkdir(step=entry_step, index=entry_index),
                                      'outputs',
                                      f'{chip.design}.pkg.json')
        reconnect_cmd = f'sc-remote -cfg {entry_manifest} -reconnect'
        cancel_cmd = f'sc-remote -cfg {entry_manifest} -cancel'
        chip.logger.info('Disconnecting from remote job')
        chip.logger.info(f'To reconnect to this job use: {reconnect_cmd}')
        chip.logger.info(f'To cancel this job use: {cancel_cmd}')
        raise SiliconCompilerError('Job canceled by user keyboard interrupt')


###################################
def __remote_run_loop(chip, check_interval):
    # Check the job's progress periodically until it finishes.
    is_busy = True
    all_nodes = nodes_to_execute(chip)
    completed = []
    result_procs = []

    def schedule_download(node):
        node_proc = multiprocessor.Process(target=fetch_results,
                                           args=(chip, node))
        node_proc.start()
        result_procs.append(node_proc)
        if node is None:
            node = 'final result'
        chip.logger.info(f'    {node}')

    while is_busy:
        time.sleep(check_interval)
        new_completed, is_busy = check_progress(chip)
        nodes_to_fetch = []
        for node in new_completed:
            if node not in completed:
                nodes_to_fetch.append(node)
                completed.append(node)
        if nodes_to_fetch:
            chip.logger.info('  Fetching completed results:')
            for node in nodes_to_fetch:
                schedule_download(node)

    # Done: try to fetch any node results which still haven't been retrieved.
    chip.logger.info('Remote job completed! Retrieving final results...')
    for step, index in all_nodes:
        if f'{step}{index}' not in completed:
            schedule_download(f'{step}{index}')
    schedule_download(None)

    # Make sure all results are fetched before letting the client issue
    # a deletion request.
    for proc in result_procs:
        proc.join()

    # Read in node manifests
    for step, index in all_nodes:
        manifest = os.path.join(chip.getworkdir(step=step, index=index),
                                'outputs',
                                f'{chip.design}.pkg.json')
        if os.path.exists(manifest):
            chip.schema.read_journal(manifest)

    # Un-set the 'remote' option to avoid from/to-based summary/show errors
    chip.unset('option', 'remote')


###################################
def check_progress(chip):
    try:
        is_busy_info = is_job_busy(chip)
        is_busy = is_busy_info['busy']
        completed = []
        if is_busy:
            completed = _process_progress_info(chip,
                                               is_busy_info)
        return completed, is_busy
    except Exception as e:
        # Sometimes an exception is raised if the request library cannot
        # reach the server due to a transient network issue.
        # Retrying ensures that jobs don't break off when the connection drops.
        chip.logger.info(f"Unknown network error encountered: retrying: {e}")
        return [], True


###################################
def _update_entry_manifests(chip):
    '''
    Helper method to update locally-run manifests to include remote job ID.
    '''

    flow = chip.get('option', 'flow')
    jobid = chip.get('record', 'remoteid')
    design = chip.get('design')

    entry_nodes = _get_flowgraph_entry_nodes(chip, flow)
    for step, index in entry_nodes:
        manifest_path = os.path.join(chip.getworkdir(step=step, index=index),
                                     'outputs',
                                     f'{design}.pkg.json')
        tmp_schema = Schema(manifest=manifest_path)
        tmp_schema.set('record', 'remoteid', jobid)
        tmp_schema.set('option', 'from', chip.get('option', 'from'))
        tmp_schema.set('option', 'to', chip.get('option', 'to'))
        with open(manifest_path, 'w') as new_manifest:
            tmp_schema.write_json(new_manifest)


###################################
def _request_remote_run(chip):
    '''
    Helper method to make a web request to start a job stage.
    '''

    remote_resume = (chip.get('option', 'resume') and chip.get('record', 'remoteid'))
    # Only package and upload the entry steps if starting a new job.
    if not remote_resume:
        upload_file = tempfile.TemporaryFile(prefix='sc', suffix='remote.tar.gz')
        with tarfile.open(fileobj=upload_file, mode='w:gz') as tar:
            tar.add(chip.getworkdir(), arcname='')
        # Flush file to ensure everything is written
        upload_file.flush()

    remote_status = _remote_ping(chip)

    if remote_status['status'] != 'ready':
        raise SiliconCompilerError('Remote server is not available.', chip=chip)

    __print_tos(chip, remote_status)

    if 'pre_upload' in remote_status:
        chip.logger.info(remote_status['pre_upload']['message'])
        time.sleep(remote_status['pre_upload']['delay'])

    # Make the actual request, streaming the bulk data as a multipart file.
    # Redirected POST requests are translated to GETs. This is actually
    # part of the HTTP spec, so we need to manually follow the trail.
    post_params = {
        'chip_cfg': chip.schema.cfg,
        'params': __build_post_params(chip,
                                      False,
                                      job_hash=chip.get('record', 'remoteid'))
    }

    post_files = {'params': json.dumps(post_params)}
    if not remote_resume:
        post_files['import'] = upload_file
        upload_file.seek(0)

    def post_action(url):
        return requests.post(url,
                             files=post_files,
                             timeout=__timeout)

    def success_action(resp):
        return resp.json()

    resp = __post(chip, '/remote_run/', post_action, success_action)
    if not remote_resume:
        upload_file.close()

    if 'message' in resp and resp['message']:
        chip.logger.info(resp['message'])
    chip.set('record', 'remoteid', resp['job_hash'])
    _update_entry_manifests(chip)
    chip.logger.info(f"Your job's reference ID is: {resp['job_hash']}")

    return remote_status['progress_interval']


###################################
def is_job_busy(chip):
    '''
    Helper method to make an async request asking the remote server
    whether a job is busy, or ready to accept a new step.
    Returns True if the job is busy, False if not.
    '''

    # Make the request and print its response.
    def post_action(url):
        params = __build_post_params(chip,
                                     False,
                                     job_hash=chip.get('record', 'remoteid'),
                                     job_name=chip.get('option', 'jobname'))
        return requests.post(url,
                             data=json.dumps(params),
                             timeout=__timeout)

    def error_action(code, msg):
        return {
            'busy': True,
            'message': ''
        }

    def success_action(resp):
        # Determine job completion based on response message, or preferably JSON parameter.
        # TODO: Only accept JSON response's "status" field once server changes are rolled out.
        is_busy = ("Job has no running steps." not in resp.text)
        try:
            json_response = json.loads(resp.text)
            if ('status' in json_response) and (json_response['status'] == 'completed'):
                is_busy = False
            elif ('status' in json_response) and (json_response['status'] == 'canceled'):
                chip.logger.info('Job was canceled.')
                is_busy = False
        except requests.JSONDecodeError:
            # Message may have been text-formatted.
            pass
        info = {
            'busy': is_busy,
            'message': resp.text
        }
        return info

    info = __post(chip,
                  '/check_progress/',
                  post_action,
                  success_action,
                  error_action=error_action)

    if not info:
        info = {
            'busy': True,
            'message': ''
        }
    return info


###################################
def cancel_job(chip):
    '''
    Helper method to request that the server cancel an ongoing job.
    '''

    def post_action(url):
        return requests.post(url,
                             data=json.dumps(__build_post_params(
                                chip,
                                False,
                                job_hash=chip.get('record', 'remoteid'))),
                             timeout=__timeout)

    def success_action(resp):
        return json.loads(resp.text)

    return __post(chip, '/cancel_job/', post_action, success_action)


###################################
def delete_job(chip):
    '''
    Helper method to delete a job from shared remote storage.
    '''

    def post_action(url):
        return requests.post(url,
                             data=json.dumps(__build_post_params(
                                chip,
                                False,
                                job_hash=chip.get('record', 'remoteid'))),
                             timeout=__timeout)

    def success_action(resp):
        return resp.text

    return __post(chip, '/delete_job/', post_action, success_action)


###################################
def fetch_results_request(chip, node, results_fd):
    '''
    Helper method to fetch job results from a remote compute cluster.
    Optional 'node' argument fetches results for only the specified
    flowgraph node (e.g. "floorplan0")

       Returns:
       * 0 if no error was encountered.
       * [response code] if the results could not be retrieved.
    '''

    # Set the request URL.
    job_hash = chip.get('record', 'remoteid')

    # Fetch results archive.
    def post_action(url):
        post_params = __build_post_params(chip, False)
        if node:
            post_params['node'] = node
        return requests.post(url,
                             data=json.dumps(post_params),
                             stream=True,
                             timeout=__timeout)

    def success_action(resp):
        shutil.copyfileobj(resp.raw, results_fd)
        return 0

    def error_action(code, msg):
        # Results are fetched in parallel, and a failure in one node
        # does not necessarily mean that the whole job failed.
        if node:
            chip.logger.warning(f'Could not fetch results for node: {node}')
        else:
            chip.logger.warning('Could not fetch results for final results.')
        return 404

    return __post(chip,
                  f'/get_results/{job_hash}.tar.gz',
                  post_action,
                  success_action,
                  error_action=error_action)


###################################
def fetch_results(chip, node):
    '''
    Helper method to fetch and open job results from a remote compute cluster.
    Optional 'node' argument fetches results for only the specified
    flowgraph node (e.g. "floorplan0")
    '''

    # Collect local values.
    job_hash = chip.get('record', 'remoteid')
    local_dir = chip.get('option', 'builddir')

    # Set default results archive path if necessary, and fetch it.
    with tempfile.TemporaryDirectory(prefix=f'sc_{job_hash}_', suffix=f'_{node}') as tmpdir:
        results_path = os.path.join(tmpdir, 'result.tar.gz')

        with open(results_path, 'wb') as rd:
            results_code = fetch_results_request(chip, node, rd)

        # Note: the server should eventually delete the results as they age out (~8h), but this will
        # give us a brief period to look at failed results.
        if results_code:
            raise SiliconCompilerError(
                "Something went wrong and your job results could not be retrieved. "
                f"(Response code: {results_code})", chip=chip)

        # Unzip the results.
        # Unauthenticated jobs get a gzip archive, authenticated jobs get nested archives.
        # So we need to extract and delete those.
        # Archive contents: server-side build directory. Format:
        # [job_hash]/[design]/[job_name]/[step]/[index]/...
        try:
            with tarfile.open(results_path, 'r:gz') as tar:
                tar.extractall(path=tmpdir)
        except tarfile.TarError as e:
            chip.logger.error(f'Failed to extract data from {results_path}: {e}')
            return

        work_dir = os.path.join(tmpdir, job_hash)
        if os.path.exists(work_dir):
            shutil.copytree(work_dir, local_dir, dirs_exist_ok=True)
        else:
            chip.logger.error(f'Empty file returned from remote for: {node}')
            return


def _remote_ping(chip):
    # Make the request and print its response.
    rcfg = __build_post_params(chip, True)

    def post_action(url):
        return requests.post(url,
                             data=json.dumps(rcfg),
                             timeout=__timeout)

    def success_action(resp):
        return resp.json()

    response_info = __post(chip, '/check_server/', post_action, success_action)
    if not response_info:
        raise ValueError('Server response is not valid.')

    return response_info


###################################
def __print_tos(chip, response_info):
    # Print terms-of-service message, if the server provides one.
    if 'terms' in response_info and response_info['terms']:
        chip.logger.info('Terms of Service info for this server:')
        for line in response_info['terms'].splitlines():
            if line:
                chip.logger.info(line)


###################################
def remote_ping(chip):
    '''
    Helper method to call check_server on server
    '''

    # Make the request and print its response.
    response_info = _remote_ping(chip)

    # Print status value.
    server_status = response_info['status']
    chip.logger.info(f'Server status: {server_status}')
    if server_status != 'ready':
        chip.logger.warning('  Status is not "ready", server cannot accept new jobs.')

    # Print server-side version info.
    version_info = response_info['versions']
    version_suffix = ' version'
    max_name_string_len = max([len(s) for s in version_info.keys()]) + len(version_suffix)
    chip.logger.info('Server software versions:')
    for name, version in version_info.items():
        print_name = f'{name}{version_suffix}'
        chip.logger.info(f'  {print_name: <{max_name_string_len}}: {version}')

    # Print user info if applicable.
    if 'user_info' in response_info:
        user_info = response_info['user_info']
        if ('compute_time' not in user_info) or \
           ('bandwidth_kb' not in user_info):
            chip.logger.info('Error fetching user information from the remote server.')
            raise ValueError(f'Server response is not valid or missing fields: {user_info}')

        remote_cfg = get_remote_config(chip, False)
        if 'username' in remote_cfg:
            # Print the user's account info, and return.
            chip.logger.info(f'User {remote_cfg["username"]}:')

        time_remaining = user_info["compute_time"] / 60.0
        bandwidth_remaining = user_info["bandwidth_kb"]
        chip.logger.info(f'  Remaining compute time: {(time_remaining):.2f} minutes')
        chip.logger.info(f'  Remaining results bandwidth: {bandwidth_remaining} KiB')

    __print_tos(chip, response_info)

    # Return the response info in case the caller wants to inspect it.
    return response_info


def configure(chip, server=None, port=None, username=None, password=None):

    def confirm_dialog(message):
        confirmed = False
        while not confirmed:
            oin = input(f'{message} y/N: ')
            if (not oin) or (oin == 'n') or (oin == 'N'):
                return False
            elif (oin == 'y') or (oin == 'Y'):
                return True
        return False

    default_server_name = urllib.parse.urlparse(default_server).hostname

    # Find the config file/directory path.
    cfg_file = chip.get('option', 'credentials')
    if not cfg_file:
        cfg_file = default_credentials_file()
    cfg_dir = os.path.dirname(cfg_file)

    # Create directory if it doesn't exist.
    if cfg_dir and not os.path.isdir(cfg_dir):
        os.makedirs(cfg_dir, exist_ok=True)

    # If an existing config file exists, prompt the user to overwrite it.
    if os.path.isfile(cfg_file):
        if not confirm_dialog('Overwrite existing remote configuration?'):
            return

    config = {}

    # If a command-line argument is passed in, use that as a public server address.
    if server:
        srv_addr = server
        chip.logger.info(f'Creating remote configuration file for server: {srv_addr}')
    else:
        # If no arguments were passed in, interactively request credentials from the user.
        srv_addr = input('Remote server address (leave blank to use default server):\n')
        srv_addr = srv_addr.replace(" ", "")

    if not srv_addr:
        srv_addr = default_server
        chip.logger.info(f'Using {srv_addr} as server')

    server = urllib.parse.urlparse(srv_addr)
    has_scheme = True
    if not server.hostname:
        # fake add a scheme to the url
        has_scheme = False
        server = urllib.parse.urlparse('https://' + srv_addr)
    if not server.hostname:
        raise ValueError(f'Invalid address provided: {srv_addr}')

    if has_scheme:
        config['address'] = f'{server.scheme}://{server.hostname}'
    else:
        config['address'] = server.hostname

    public_server = default_server_name in srv_addr
    if public_server and not confirm_dialog(__tos_str):
        return

    if server.port is not None:
        config['port'] = server.port

    if not public_server:
        if username is None:
            username = server.username
            if username is None:
                username = input('Remote username (leave blank for no username):\n')
                username = username.replace(" ", "")
        if password is None:
            password = server.password
            if password is None:
                password = input('Remote password (leave blank for no password):\n')
                password = password.replace(" ", "")

        if username:
            config['username'] = username
        if password:
            config['password'] = password

    # Save the values to the target config file in JSON format.
    with open(cfg_file, 'w') as f:
        f.write(json.dumps(config, indent=4))

    # Let the user know that we finished successfully.
    chip.logger.info(f'Remote configuration saved to: {cfg_file}')
