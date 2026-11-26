"""sys.path wiring for the nos_authentik tests."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os
import sys


# Ensure the playbook root is on sys.path so ``module_utils.nos_authentik_client``
# and the ``library.nos_authentik`` module resolve the same way Ansible sees them.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
