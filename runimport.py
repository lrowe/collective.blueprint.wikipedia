import os
from collective.transmogrifier.transmogrifier import Transmogrifier
from collective.transmogrifier.transmogrifier import configuration_registry

filepath = os.environ['RECIPE']
filename = os.path.basename(filepath)
configuration_registry.registerConfiguration(
            filename, filename, filepath, filepath)

#Transmogrifier._raw = []  # TODO: bad bad boy, put this upstream
try:
    Transmogrifier(portal)(filename)
except:
    import ipdb, sys
    e, m, tb = sys.exc_info()
    print m
    ipdb.post_mortem(tb)


