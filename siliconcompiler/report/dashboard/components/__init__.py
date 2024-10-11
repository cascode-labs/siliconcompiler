import base64
import gzip
import json
import os
import pandas

import streamlit
from streamlit_agraph import agraph
import streamlit_antd_components as sac

from PIL import Image

from siliconcompiler import __version__ as sc_version
from siliconcompiler import utils, sc_open
from siliconcompiler.report import report

from siliconcompiler.report.dashboard import state
from siliconcompiler.report.dashboard.components import flowgraph


SC_ABOUT = [
    f"SiliconCompiler {sc_version}",
    '''A compiler framework that automates translation from source code to
     silicon.''',
    "https://www.siliconcompiler.com/",
    "https://github.com/siliconcompiler/siliconcompiler/"
]
SC_MENU = {
    "Get help": "https://docs.siliconcompiler.com/",
    "Report a Bug":
    '''https://github.com/siliconcompiler/siliconcompiler/issues''',
    "About": "\n\n".join(SC_ABOUT)}
SC_DATA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data'))
SC_LOGO_PATH = os.path.join(SC_DATA_ROOT, 'logo.png')
SC_FONT_PATH = os.path.join(SC_DATA_ROOT, 'RobotoMono', 'RobotoMono-Regular.ttf')

MAX_DICT_ITEMS_TO_SHOW = 100
MAX_FILE_LINES_TO_SHOW = 10000


def _check_if_file_is_binary(path, compressed):
    # Read first chunk and check for non characters
    try:
        if compressed:
            with gzip.open(path, 'rt') as f:
                f.read(8196)
        else:
            with open(path, "r") as f:
                f.read(8196)
    except UnicodeDecodeError:
        return True
    return False


def _read_file(path):
    _, compressed_file_extension = os.path.splitext(path.lower())
    file_info = []

    ext = utils.get_file_ext(path)
    honor_max_file = ext not in ('json', )

    def read_file(fid):
        for line in fid:
            file_info.append(line.rstrip())
            if honor_max_file and len(file_info) >= MAX_FILE_LINES_TO_SHOW:
                file_info.append('... truncated ...')
                return

    is_compressed = compressed_file_extension == '.gz'
    if _check_if_file_is_binary(path, is_compressed):
        return "Binary file"

    if is_compressed:
        with gzip.open(path, 'rt') as fid:
            read_file(fid)
    else:
        with sc_open(path) as fid:
            read_file(fid)

    return "\n".join(file_info)


def _detect_file_type(ext):
    if ext in ("v", "vh", "sv", "svh", "vg"):
        return "verilog"
    if ext in ("vhdl", "vhd"):
        return "vhdl"
    if ext in ("tcl", "sdc", "xdc"):
        return "tcl"
    if ext in ("c", "cpp", "cc", "h"):
        return "cpp"
    if ext in ("csv",):
        return "csv"
    if ext in ("md",):
        return "markdown"
    if ext in ("sh",):
        return "bash"

    return "log"


def _convert_filepaths_to_select_tree(logs_and_reports):
    """
    Converts the logs_and_reports found to the structure
    required by streamlit_tree_select. Success is predicated on the order of
    logs_and_reports outlined in report.get_files.

    Args:
        logs_and_reports (list) : A list of 3-tuples with order of a path name,
            folder in the..., and files in the....
    """
    if not logs_and_reports:
        return []

    all_files = {}
    for path_name, folders, files in logs_and_reports:
        all_files[path_name] = {
            'files': list(files),
            'folders': list(folders)
        }

    def organize_node(base_folder):
        nodes = []

        for folder in all_files[base_folder]['folders']:
            path = os.path.join(base_folder, folder)
            nodes.append({
                'value': path,
                'label': folder,
                'children': organize_node(path)
            })
        for file in all_files[base_folder]['files']:
            nodes.append({
                'value': os.path.join(base_folder, file),
                'label': file
            })

        return nodes

    starting_path_name = logs_and_reports[0][0]
    return organize_node(starting_path_name)


def page_header(title_col_width=0.7):
    """
    Displays the title and a selectbox that allows you to select a given run
    to inspect.

    Args:
        title_col_width (float) : A number between 0 and 1 which is the percentage of the
            width of the screen given to the title and logo. The rest is given to selectbox.
    """
    title_col, job_select_col = \
        streamlit.columns([title_col_width, 1 - title_col_width], gap="large")
    with title_col:
        design_title(design=state.get_chip().design)
    with job_select_col:
        job_selector()


def design_title(design=""):
    streamlit.markdown(
        '''
<head>
    <style>
        /* Define the @font-face rule */
        @font-face {
        font-family: 'Roboto Mono';
        src: url(SC_FONT_PATH) format('truetype');
        font-weight: normal;
        font-style: normal;
        }

        /* Styles for the logo and text */
        .logo-container {
        display: flex;
        align-items: flex-start;
        }

        .logo-image {
        margin-right: 10px;
        margin-top: -10px;
        }

        .logo-text {
        display: flex;
        flex-direction: column;
        margin-top: -20px;
        }

        .design-text {
        color: #F1C437; /* Yellow color */
        font-family: 'Roboto Mono', sans-serif;
        font-weight: 700 !important;
        font-size: 30px !important;
        margin-bottom: -16px;
        }

        .dashboard-text {
        color: #1D4482; /* Blue color */
        font-family: 'Roboto Mono', sans-serif;
        font-weight: 700 !important;
        font-size: 30px !important;
        }

    </style>
</head>
        ''',
        unsafe_allow_html=True
    )

    logo = base64.b64encode(open(SC_LOGO_PATH, "rb").read()).decode()
    streamlit.markdown(
        f'''
<body>
    <div class="logo-container">
        <img src="data:image/png;base64,{logo}" alt="SiliconCompiler logo"
             class="logo-image" height="61">
        <div class="logo-text">
            <p class="design-text">{design}</p>
            <p class="dashboard-text">dashboard</p>
        </div>
    </div>
</body>
        ''',
        unsafe_allow_html=True
    )


def job_selector():
    job = streamlit.selectbox(
        'pick a job',
        state.get_chips(),
        label_visibility='collapsed')

    current_job = streamlit.session_state[state.SELECTED_JOB]
    streamlit.session_state[state.SELECTED_JOB] = job
    if current_job != job:
        # Job changed, so need to run
        streamlit.rerun()


def setup_page(design):
    streamlit.set_page_config(
        page_title=f'{design} dashboard',
        page_icon=Image.open(SC_LOGO_PATH),
        layout="wide",
        menu_items=SC_MENU)


def file_viewer(chip, path, header_col_width=0.89):
    if not path:
        streamlit.error('Select a file')
        return

    if not os.path.isfile(path):
        streamlit.error(f'{path} is not a file')
        return

    # Detect file type
    relative_path = os.path.relpath(path, chip.getworkdir())
    filename = os.path.basename(path)
    file_extension = utils.get_file_ext(path)

    # Build streamlit module
    header_col, download_col = \
        streamlit.columns([header_col_width, 1 - header_col_width], gap='small')

    with header_col:
        streamlit.header(relative_path)

    with download_col:
        streamlit.markdown(' ')  # aligns download button with title
        streamlit.download_button(
            label="Download",
            data=path,
            file_name=filename)

    try:
        if file_extension in ('jpg', 'jpeg', 'png'):
            # Data is an image
            streamlit.image(path)
        elif file_extension == 'json':
            # Data is a json file
            data = json.loads(_read_file(path))
            expand_keys = report.get_total_manifest_key_count(data) < MAX_DICT_ITEMS_TO_SHOW
            streamlit.json(data, expanded=expand_keys)
        else:
            # Assume file is text
            streamlit.code(
                _read_file(path),
                language=_detect_file_type(file_extension),
                line_numbers=True)
    except Exception as e:
        streamlit.markdown(f'Error occurred reading file: {e}')


def manifest_viewer(
        simplified_manifest,
        full_manifest,
        header_col_width=0.70):
    """
    Displays the manifest and a way to search through the manifest.

    Args:
        simplified_manifest (dict) : Layered dictionary containing a filtered version of the
            chip.schema.cfg
        full_manifest (dict) : Copy of chip.schema.cfg
        header_col_width (float) : A number between 0 and 1 which is the maximum
            percentage of the width of the screen given to the header. The rest
            is given to the settings and download buttons.
    """
    end_column_widths = (1 - header_col_width) / 2
    header_col, settings_col, download_col = \
        streamlit.columns(
            [header_col_width, end_column_widths, end_column_widths],
            gap='small')
    with header_col:
        streamlit.header('Manifest')

    with settings_col:
        streamlit.markdown(' ')  # aligns with title
        with streamlit.popover("Settings"):
            if streamlit.checkbox(
                    'Raw manifest',
                    help='Click here to see the manifest before it was made more readable'):
                manifest_to_show = full_manifest
            else:
                manifest_to_show = simplified_manifest

            if streamlit.checkbox(
                    'Hide empty values',
                    help='Hide empty keypaths',
                    value=True):
                manifest_to_show = report.search_manifest(
                    manifest_to_show,
                    value_search='*')

            search_key = streamlit.text_input('Search Keys', '', placeholder="Keys")
            search_value = streamlit.text_input('Search Values', '', placeholder="Values")

            manifest_to_show = report.search_manifest(
                manifest_to_show,
                key_search=search_key,
                value_search=search_value)

    with download_col:
        streamlit.markdown(' ')  # aligns with title
        streamlit.download_button(
            label='Download',
            file_name='manifest.json',
            data=json.dumps(full_manifest, indent=2),
            mime="application/json")

    expand_keys = report.get_total_manifest_key_count(manifest_to_show) < MAX_DICT_ITEMS_TO_SHOW
    streamlit.json(manifest_to_show, expanded=expand_keys)


def metrics_viewer(metric_dataframe, metric_to_metric_unit_map, header_col_width=0.7):
    """
    Displays multi-select check box to the users which allows them to select
    which nodes and metrics to view in the dataframe.

    Args:
        metric_dataframe (Pandas.DataFrame) : Contains the metrics of all nodes.
        metric_to_metric_unit_map (dict) : Maps the metric to the associated metric unit.
    """

    all_nodes = metric_dataframe.columns.tolist()
    all_metrics = list(metric_to_metric_unit_map.values())

    header_col, settings_col = streamlit.columns(
        [header_col_width, 1 - header_col_width],
        gap="large")
    with header_col:
        streamlit.header('Metrics')
    with settings_col:
        # Align to header
        streamlit.markdown('')

        with streamlit.popover("Settings"):
            transpose = streamlit.checkbox(
                'Transpose',
                help='Transpose the metrics table')

            display_nodes = streamlit.multiselect('Pick nodes to include', all_nodes, [])
            display_metrics = streamlit.multiselect('Pick metrics to include?', all_metrics, [])

    # Filter data
    if not display_nodes:
        display_nodes = all_nodes

    if not display_metrics:
        display_metrics = all_metrics

    dataframe_nodes = list(display_nodes)
    dataframe_metrics = []
    for metric in metric_dataframe.index.tolist():
        if metric_to_metric_unit_map[metric] in display_metrics:
            dataframe_metrics.append(metric)

    metric_dataframe = metric_dataframe.loc[dataframe_metrics, dataframe_nodes]
    if transpose:
        metric_dataframe = metric_dataframe.transpose()

    # TODO By July 2024, Streamlit will let catch click events on the dataframe
    streamlit.dataframe(metric_dataframe, use_container_width=True)


def node_file_tree_viewer(chip, step, index):
    logs_and_reports = _convert_filepaths_to_select_tree(
        report.get_files(chip, step, index))

    if not logs_and_reports:
        streamlit.markdown("No files to show")

    lookup = {}
    tree_items = []

    file_metrics = report.get_metrics_source(chip, step, index)
    work_dir = chip.getworkdir(step=step, index=index)

    def make_item(file):
        lookup[file['value']] = file['label']
        item = sac.TreeItem(file['value'], icon='file', tag=[], children=[])

        ext = utils.get_file_ext(file['value'])
        file_type = _detect_file_type(ext)

        if file['value'].endswith('.pkg.json'):
            item.icon = 'boxes'
        elif ext in ('png', 'jpg', 'jpeg'):
            item.icon = 'file-image'
        elif ext == 'json':
            item.icon = 'file-json'
        elif file_type in ('verilog', 'tcl', 'vhdl', 'cpp', 'bash'):
            item.icon = 'file-code'
        elif ext in ('log', 'rpt', 'drc', 'warnings', 'errors'):
            item.icon = 'file-text'
        else:
            item.icon = 'file'

        check_file = os.path.relpath(file['value'], work_dir)
        if check_file in file_metrics:
            for metric in file_metrics[check_file]:
                if len(item.tag) < 5:
                    item.tag.append(sac.Tag(metric, color='green'))
                else:
                    item.tag.append(sac.Tag('metrics...', color='geekblue'))
                    break
            item.tooltip = "metrics: " + ", ".join(file_metrics[check_file])

        if 'children' in file:
            item.icon = 'folder'
            for child in file['children']:
                item.children.append(make_item(child))

        return item

    for file in logs_and_reports:
        tree_items.append(make_item(file))

    def format_label(value):
        return lookup[value]

    selected = sac.tree(
        items=tree_items,
        format_func=format_label,
        size='md',
        icon='table',
        open_all=True)

    if selected and os.path.isfile(selected):
        streamlit.session_state[state.SELECTED_FILE] = selected
    else:
        streamlit.session_state[state.SELECTED_FILE] = None


def node_viewer(chip, step, index, metric_dataframe):
    metrics_col, records_col, logs_and_reports_col = streamlit.columns(3, gap='small')

    node_name = f'{step}{index}'

    with metrics_col:
        streamlit.subheader(f'{node_name} metrics')
        if node_name in metric_dataframe:
            streamlit.dataframe(metric_dataframe[node_name].dropna(), use_container_width=True)
    with records_col:
        streamlit.subheader(f'{step}{index} details')
        nodes = {}
        nodes[step + index] = report.get_flowgraph_nodes(chip, step, index)
        streamlit.dataframe(pandas.DataFrame.from_dict(nodes), use_container_width=True)
    with logs_and_reports_col:
        streamlit.subheader(f'{step}{index} files')
        node_file_tree_viewer(chip, step, index)


def flowgraph_viewer(chip):
    '''
    This function creates, displays, and returns the selected node of the flowgraph.

    Args:
        chip (Chip) : The chip object that contains the schema read from.
    '''

    nodes, edges = flowgraph.get_nodes_and_edges(chip)
    streamlit.session_state[state.SELECTED_FLOWGRAPH_NODE] = agraph(
        nodes=nodes,
        edges=edges,
        config=flowgraph.get_graph_config())


def node_selector(nodes):
    """
    Displays selectbox for nodes to show in the node information panel. Since
    both the flowgraph and selectbox show which node's information is
    displayed, the one clicked more recently will be displayed.

    Args:
        nodes (list) : Contains the metrics of all nodes.
    """
    node_from_flowgraph = streamlit.session_state[state.SELECTED_FLOWGRAPH_NODE]
    prev_node = streamlit.session_state[state.SELECTED_NODE]
    streamlit.session_state[state.SELECTED_NODE] = None

    with streamlit.popover("Select Node"):
        # Preselect node
        idx = 0
        if prev_node:
            idx = nodes.index(prev_node)
        if node_from_flowgraph:
            idx = nodes.index(node_from_flowgraph)
        newnode = streamlit.selectbox(
            'Pick a node to inspect',
            nodes,
            index=idx)

        if newnode and newnode != node_from_flowgraph:
            streamlit.session_state[state.SELECTED_NODE] = newnode

    if not streamlit.session_state[state.SELECTED_NODE]:
        streamlit.session_state[state.SELECTED_NODE] = node_from_flowgraph

    if prev_node != streamlit.session_state[state.SELECTED_NODE]:
        streamlit.rerun()