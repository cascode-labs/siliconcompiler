################################
# Tool Setup
################################

def setup_toool(chip, stage, tool):

     refdir = 'eda/vpr/'

     #Default stages
     chip.add('tool', stage, 'threads', '4')
     chip.add('tool', stage, 'format', 'cmdline')
     chip.add('tool', stage, 'copy', 'false')
     chip.add('tool', stage, 'vendor', 'vpr')
     chip.add('tool', stage, 'refdir', '')
     chip.add('tool', stage, 'script', '')
     
     #TODO: break up into stages later
     if stage in ("floorplan"):          
          chip.add('tool', stage, 'exe', 'vpr')
     else:
          #ignore stages withh echo
          chip.add('tool', stage, 'exe', 'echo')
          
def setup_options(chip, stage, tool):

     arch = chip.get('fpga_arch')
     topmodule = chip.get('design')     
     blif = "inputs/" + topmodule + ".blif"     
     options = arch + blif

     return options

################################
# Pre/Post Processing
################################

def pre_process(chip, step, tool):
    ''' Tool specific function to run before step execution
    '''
    pass

def post_process(chip, step, tool):
    ''' Tool specific function to run after step execution
    '''
    pass
