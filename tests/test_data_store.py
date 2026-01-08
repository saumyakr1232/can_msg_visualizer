import unittest
import sys
import os
from pathlib import Path

# Add src to path to allow imports
sys.path.append(str(Path(__file__).parent.parent / "src"))

from can_visualizer.core.data_store import DataStore
from can_visualizer.core.models import DecodedSignal


class TestDataStore(unittest.TestCase):
    def setUp(self):
        self.store = DataStore()
        self.signals = [
            DecodedSignal(
                timestamp=1.0,
                message_name="Msg1",
                message_id=0x100,
                signal_name="SigA",
                raw_value=10,
                physical_value=10.0,
                unit="V",
            ),
            DecodedSignal(
                timestamp=2.0,
                message_name="Msg1",
                message_id=0x100,
                signal_name="SigB",
                raw_value=20,
                physical_value=20.0,
                unit="A",
            ),
            DecodedSignal(
                timestamp=3.0,
                message_name="Msg2",
                message_id=0x200,
                signal_name="SigA",
                raw_value=30,
                physical_value=30.0,
                unit="V",
            ),
            DecodedSignal(
                timestamp=4.0,
                message_name="Msg2",
                message_id=0x200,
                signal_name="SigC",
                raw_value=40,
                physical_value=40.0,
                unit="C",
            ),
        ]
        self.store.add_data(self.signals)

    def tearDown(self):
        self.store.close()

    def test_total_count(self):
        self.assertEqual(self.store.get_total_count(), 4)

    def test_fetch_all(self):
        fetched = list(self.store.fetch_data())
        self.assertEqual(len(fetched), 4)
        self.assertEqual(fetched[0].timestamp, 1.0)
        self.assertEqual(fetched[3].timestamp, 4.0)

    def test_fetch_limit(self):
        fetched = list(self.store.fetch_data(limit=2))
        self.assertEqual(len(fetched), 2)
        self.assertEqual(fetched[0].timestamp, 1.0)
        self.assertEqual(fetched[1].timestamp, 2.0)

    def test_fetch_paginated(self):
        # Page 1, size 2
        page1 = list(self.store.fetch_paginated_data(page=1, page_size=2))
        self.assertEqual(len(page1), 2)
        self.assertEqual(page1[0].timestamp, 1.0)
        self.assertEqual(page1[1].timestamp, 2.0)

        # Page 2, size 2
        page2 = list(self.store.fetch_paginated_data(page=2, page_size=2))
        self.assertEqual(len(page2), 2)
        self.assertEqual(page2[0].timestamp, 3.0)
        self.assertEqual(page2[1].timestamp, 4.0)

        # Page 3, size 2 (empty)
        page3 = list(self.store.fetch_paginated_data(page=3, page_size=2))
        self.assertEqual(len(page3), 0)

    def test_fetch_by_signal(self):
        sig_a = list(self.store.fetch_by_signal("SigA"))
        self.assertEqual(len(sig_a), 2)
        self.assertEqual(sig_a[0].message_name, "Msg1")
        self.assertEqual(sig_a[1].message_name, "Msg2")

        sig_b = list(self.store.fetch_by_signal("SigB"))
        self.assertEqual(len(sig_b), 1)

        sig_none = list(self.store.fetch_by_signal("NonExistent"))
        self.assertEqual(len(sig_none), 0)

    def test_get_signal_names(self):
        names = self.store.get_signal_names()
        self.assertEqual(len(names), 3)
        self.assertIn("SigA", names)
        self.assertIn("SigB", names)
        self.assertIn("SigC", names)

    def test_clear(self):
        self.store.clear()
        self.assertEqual(self.store.get_total_count(), 0)
        self.assertEqual(len(list(self.store.fetch_data())), 0)


if __name__ == "__main__":
    unittest.main()
