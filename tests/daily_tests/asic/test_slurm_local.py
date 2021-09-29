import os
import siliconcompiler

if __name__ != "__main__":
    from tests.fixtures import test_wrapper

##################################
def test_slurm_local_py():
    '''Basic Python API test: build the GCD example using only Python code.
    '''

    # Create instance of Chip class
    chip = siliconcompiler.Chip()

    gcd_ex_dir = os.path.abspath(__file__)
    gcd_ex_dir = gcd_ex_dir[:gcd_ex_dir.rfind('/tests/daily_tests/asic')] + '/examples/gcd/'

    # Inserting value into configuration
    chip.set('design', 'gcd', clobber=True)
    chip.target("freepdk45_asicflow")
    chip.add('source', gcd_ex_dir + 'gcd.v')
    chip.set('clock', 'clock_name', 'pin', 'clk')
    chip.add('constraint', gcd_ex_dir + 'gcd.sdc')
    chip.set('asic', 'diearea', [(0,0), (100.13,100.8)])
    chip.set('asic', 'corearea', [(10.07,11.2), (90.25,91)])
    chip.set('jobscheduler', 'slurm')
    chip.set('quiet', 'true', clobber=True)
    chip.set('relax', 'true', clobber=True)

    # Run the chip's build process synchronously.
    chip.run()

    # (Printing the summary makes it harder to see other test case results.)
    #chip.summary()

    # Verify that GDS and SVG files were generated.
    assert os.path.isfile('build/gcd/job0/export0/outputs/gcd.gds')

if __name__ == "__main__":
    test_gcd_local_py()
