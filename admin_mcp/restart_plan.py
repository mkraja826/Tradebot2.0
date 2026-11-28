"""Offline command planner. Never invokes subprocesses."""
from types import MappingProxyType

# Deliberately fixture-only until production service identities and safety
# interlocks are independently verified.
SERVICES=MappingProxyType({"fixture":"recover-admin-fixture.service"})

def restart_plan(target):
    if type(target) is not str or target not in SERVICES:
        raise ValueError("service not allowed")
    return ("/usr/bin/systemctl","restart","--",SERVICES[target])

def status_plan(target):
    if type(target) is not str or target not in SERVICES:
        raise ValueError("service not allowed")
    return ("/usr/bin/systemctl","show","--property=ActiveState,SubState,Result","--",SERVICES[target])
