"""Load the fixed anchors.py and veribim_geom.py in place of the installed ones.

The shadowing lives only inside the importing process: the fixed files are
registered under the installed module names before anything else imports them,
so the generator's goldlib._geom() and every other caller see the fixed code.
Nothing under code/ is written.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = 'code'
os.environ['MODIFC_GEOM_CACHE'] = os.path.join(HERE, 'geom_cache')
for p in (CODE + '/harness', CODE):
    if p not in sys.path:
        sys.path.insert(0, p)
sys.dont_write_bytecode = True


def _load(name, filename):
    if name in sys.modules:
        raise RuntimeError('%s was imported before the fixed copy was loaded' % name)
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    parent, _, child = name.rpartition('.')
    setattr(sys.modules[parent], child, module)
    return module


if os.environ.get('OPPOSITE_FIX_USE_INSTALLED'):
    # After the install: run the same tests on the installed modules, and check
    # they are byte-identical to the fixed copies tested here.
    import hashlib
    from modifc_harness import veribim_geom as geom  # noqa: E402
    from modifc_gen import anchors  # noqa: E402
    for module, filename in ((geom, 'veribim_geom_fixed.py'), (anchors, 'anchors_fixed.py')):
        mine = hashlib.sha256(open(os.path.join(HERE, filename), 'rb').read()).hexdigest()
        installed = hashlib.sha256(open(module.__file__, 'rb').read()).hexdigest()
        assert mine == installed, '%s differs from %s' % (module.__file__, filename)
else:
    import modifc_harness  # noqa: E402
    geom = _load('modifc_harness.veribim_geom', 'veribim_geom_fixed.py')
    import modifc_gen  # noqa: E402
    anchors = _load('modifc_gen.anchors', 'anchors_fixed.py')
from modifc_gen.scene import Scene, FAMILY_CLASS  # noqa: E402,F401
from modifc_gen import goldlib  # noqa: E402
assert goldlib._geom() is geom, 'goldlib does not see the fixed library'
