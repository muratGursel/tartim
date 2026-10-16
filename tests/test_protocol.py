import random
import unittest
from datetime import datetime

from tartim.protocol import Framer, parse
from tartim.simulator import synthetic_record

# SYNTHETIC sample: the field codes mimic the MC-780 format, the values are made up.
SAMPLE = ('{0,16,~0,1,~1,1,~2,1,MO,"MC-780",ID,"0000000000000042",St,0,'
          'Da,"16/10/2026",TI,"09:30",Bt,0,GE,2,AG,34,Hm,165.0,Pt,0.5,'
          'Wk,62.4,MI,22.9,FW,27.1,fW,16.9,MW,45.5,mW,43.2,bW,2.3,IF,4,rB,1350,'
          'XX,"yeni",CS,5C}')


class ParseTests(unittest.TestCase):
    def test_parses_known_fields(self):
        m = parse(SAMPLE)
        self.assertTrue(m.recognized)
        self.assertEqual(m.model, "MC-780")
        self.assertEqual(m.subject_id, "42")
        self.assertEqual(m.weight, 62.4)
        self.assertEqual(m.values["FW"], 27.1)
        self.assertEqual(m.values["fW"], 16.9)  # case sensitive
        self.assertEqual(m.values["IF"], 4)
        self.assertEqual(m.measured_at(), datetime(2026, 10, 16, 9, 30))

    def test_keeps_unknown_fields(self):
        self.assertEqual(parse(SAMPLE).values["XX"], "yeni")

    def test_unrecognized_format_keeps_raw(self):
        for raw in ("1,2,3,4", "", "Wk,70.0,FW", "hello world"):
            m = parse(raw)
            self.assertFalse(m.recognized, raw)
            self.assertEqual(m.raw, raw)

    def test_broken_pair_sequence_is_unrecognized(self):
        self.assertFalse(parse("MO,MC-780,Wk,70.0,12.5,FW,20").recognized)

    def test_record_without_braces(self):
        m = parse('MO,"BC-418",Wk,80.2,FW,25.0')
        self.assertEqual((m.model, m.weight), ("BC-418", 80.2))

    def test_synthetic_records_round_trip(self):
        rng = random.Random(1)
        for i in range(50):
            m = parse(synthetic_record(subject=i + 1, rng=rng))
            self.assertTrue(m.recognized)
            self.assertEqual(m.subject_id, str(i + 1))


class FramerTests(unittest.TestCase):
    def test_splits_chunks_byte_by_byte(self):
        stream = (SAMPLE + "\r\n" + SAMPLE + "\r\n").encode()
        framer = Framer()
        records = []
        for b in stream:
            records += framer.feed(bytes([b]))
        self.assertEqual(records, [SAMPLE, SAMPLE])

    def test_braced_record_spanning_lines(self):
        framer = Framer()
        records = framer.feed(b'{MO,"MC-780",\r\nWk,70.0}\r\n')
        self.assertEqual(len(records), 1)
        self.assertEqual(parse(records[0]).weight, 70.0)

    def test_plain_lines_and_flush(self):
        framer = Framer()
        self.assertEqual(framer.feed(b"a,1\nb,2\r\nc"), ["a,1", "b,2"])
        self.assertEqual(framer.flush(), ["c"])

    def test_buffer_is_bounded(self):
        framer = Framer(max_len=100)
        records = framer.feed(b"{" + b"x" * 200)
        self.assertEqual(len(records), 1)
        self.assertEqual(framer.flush(), [])


if __name__ == "__main__":
    unittest.main()
