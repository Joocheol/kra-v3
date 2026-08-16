import unittest
import analyze_flb_preservation_virtual_cap as diag

class FLBPreservationTrigger(unittest.TestCase):
    def test_run_diagnostic(self):
        diag.main()

if __name__ == '__main__':
    unittest.main()
