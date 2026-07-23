import sys


# Plugin source is packaged directly from the working tree. Keep validation
# runs from depositing bytecode inside the distributable plugin directory.
sys.dont_write_bytecode = True
