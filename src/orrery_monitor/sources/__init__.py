from __future__ import annotations

from orrery_monitor.models import SourceAdapter
from orrery_monitor.sources.dot_wpc import DotWPCAdapter
from orrery_monitor.sources.drdo import DRDOAdapter
from orrery_monitor.sources.fcc_icfs import FCCICFSAdapter
from orrery_monitor.sources.idex import IDEXAdapter
from orrery_monitor.sources.inspace import INSpaceAdapter
from orrery_monitor.sources.isro import ISROAdapter
from orrery_monitor.sources.nsil import NSILAdapter
from orrery_monitor.sources.parliament_space import ParliamentSpaceAdapter
from orrery_monitor.sources.pib_space import PIBSpaceAdapter


def load_adapters() -> dict[str, SourceAdapter]:
    """Return adapters that have passed live inspection and fixture coverage."""

    return {
        "dot_wpc": DotWPCAdapter(),
        "drdo": DRDOAdapter(),
        "fcc_icfs": FCCICFSAdapter(),
        "idex": IDEXAdapter(),
        "inspace": INSpaceAdapter(),
        "isro": ISROAdapter(),
        "nsil": NSILAdapter(),
        "parliament_space": ParliamentSpaceAdapter(),
        "pib_space": PIBSpaceAdapter(),
    }
