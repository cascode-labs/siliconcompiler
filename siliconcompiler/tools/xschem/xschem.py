'''
Xschem is a free and open-source schematic entry software tool.  It allows
schematics to be defined hierarchically in "*.sch" and "*.sym" text files for
schematics and symbols respectively.  It can also netlist schematics.

All Xschem tasks may consumer input through the following keypath:

* :keypath:`input, schematic`

Documentation: https://xschem.sourceforge.io/stefan/index.html

Sources: https://github.com/StefanSchippers/xschem

Installation: https://xschem.sourceforge.io/stefan/xschem_man/install_xschem.html
'''
import os
from siliconcompiler import Chip
from siliconcompiler.tools._common import (
    add_frontend_requires,
    get_frontend_options,
    add_require_input,
    get_input_files,
    get_tool_task,
    input_provides
)


####################################################################
# Make Docs
####################################################################
def make_docs(chip):
    pass


def setup(chip: Chip) -> None:
    ''' Per tool function that returns a dynamic options string based on
    the dictionary settings. Static settings only.
    '''

    tool = 'xschem'
    step = chip.get('arg', 'step')
    index = chip.get('arg', 'index')
    _, task = get_tool_task(chip, step, index)

    # Basic Tool Setup
    chip.set('tool', tool, 'exe', 'xschem')
    chip.set('tool', tool, 'vswitch', '--version')
    chip.set('tool', tool, 'version', '>=3.4.0', clobber=False)

    # Common to all tasks
    # Max threads
    chip.set('tool', tool, 'task', task, 'threads', os.cpu_count(),
             step=step, index=index, clobber=False)

    # Basic warning and error grep check on logfile  
    #  TODO: Add warning / error parsing
    # chip.set('tool', tool, 'task', task, 'regex', 'warnings', r"^\%Warning",
    #          step=step, index=index, clobber=False)
    # chip.set('tool', tool, 'task', task, 'regex', 'errors', r"^\%Error",
    #          step=step, index=index, clobber=False)

    chip.set('tool', tool, 'task', task, 'file', 'config',
             'xschemrc configuration file.  It is written in TCL.',
             field='help')
    if chip.get('tool', tool, 'task', task, 'file', 'config', step=step, index=index):
        chip.add('tool', tool, 'task', task, 'require',
                 ','.join(['tool', tool, 'task', task, 'file', 'config']),
                 step=step, index=index)

    if f'{chip.top()}.sch' not in input_provides(chip, step, index):
        add_require_input(chip, 'input', 'schematic', 'path')
        # add_require_input(chip, 'input', 'rtl', 'systemverilog')
    # add_require_input(chip, 'input', 'cmdfile', 'f')
    # add_frontend_requires(chip, ['ydir', 'vlib', 'idir', 'libext', 'param', 'define'])

def runtime_options(chip: Chip):
    cmdlist = []
    tool = 'xschem'
    step = chip.get('arg', 'step')
    index = chip.get('arg', 'index')
    _, task = get_tool_task(chip, step, index)

    design = chip.top()

    has_input = os.path.isfile(f'inputs/{design}.v')
    opts_supports = ['param', 'libext']
    if not has_input:
        opts_supports.extend(['ydir', 'vlib', 'idir', 'define'])

    frontend_opts = get_frontend_options(chip, opts_supports)

    # Even though most of these don't need to be set in runtime_options() in order for the driver to
    # function properly, setting all the CLI options here facilitates a user using ['tool', <tool>,
    # 'task', <task>, 'option'] to supply additional CLI flags.

    cmdlist.append('')
    options = [
            "--quit","--no_x",
            "--netlist", "-o", str(self.netlist_filepath.parent),
            "--log", str(self.netlisting_log_path),
            "--rcfile", str(self.xschemrc_path),
            ]

    cmdlist.extend(options)

    assertions = chip.get('tool', tool, 'task', task, 'var',
                          'enable_assert', step=step, index=index)
    if assertions == ['true']:
        cmdlist.append('--assert')

    # Converting user setting to verilator specific filter
    for warning in chip.get('tool', tool, 'task', task, 'warningoff', step=step, index=index):
        cmdlist.append(f'-Wno-{warning}')

    libext = frontend_opts['libext']
    if libext:
        libext_option = f"+libext+.{'+.'.join(libext)}"
        cmdlist.append(libext_option)

    # Verilator docs recommend this file comes first in CLI arguments
    for value in chip.find_files('tool', tool, 'task', task, 'file', 'config',
                                 step=step, index=index):
        cmdlist.append(value)

    for param, value in frontend_opts['param']:
        cmdlist.append(f'-G{param}={value}')

    if os.path.isfile(f'inputs/{design}.v'):
        cmdlist.append(f'inputs/{design}.v')
    else:
        for value in frontend_opts['ydir']:
            cmdlist.append(f'-y {value}')
        for value in frontend_opts['vlib']:
            cmdlist.append(f'-v {value}')
        for value in frontend_opts['idir']:
            cmdlist.append(f'-I{value}')
        for value in frontend_opts['define']:
            if value == "VERILATOR":
                # Verilator auto defines this and will error if it is defined twice.
                continue
            cmdlist.append(f'-D{value}')
        for value in get_input_files(chip, 'input', 'rtl', 'systemverilog'):
            cmdlist.append(value)
        for value in get_input_files(chip, 'input', 'rtl', 'verilog'):
            cmdlist.append(value)

    for value in get_input_files(chip, 'input', 'cmdfile', 'f'):
        cmdlist.append(f'-f {value}')

    return cmdlist

def parse_version(stdout):
    # Example version output:
    #  XSCHEM V3.4.5
    #  Copyright (C) 1998-2023 Stefan Schipper
    return stdout.split()[1][2:]

##################################################
if __name__ == "__main__":
    chip = make_docs()
