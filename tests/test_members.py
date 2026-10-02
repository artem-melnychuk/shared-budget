import unittest

from budget.members import Members
from tests.fakes import ALEX_ID, ENV, SAM_ID, members


class MembersTest(unittest.TestCase):
    def test_from_env(self):
        m = members()
        self.assertEqual([x.key for x in m.members], ["alex", "sam"])
        self.assertEqual(m.by_user_id(SAM_ID).names, ("Sam Example", "Sammy"))

    def test_resolve_by_id_wins_over_name(self):
        self.assertEqual(members().resolve(ALEX_ID, "Sam Example").key, "alex")

    def test_resolve_hidden_author_by_name(self):
        m = members()
        self.assertEqual(m.resolve(None, "  sammy ").key, "sam")
        self.assertEqual(m.resolve(None, "SAM   example").key, "sam")
        self.assertIsNone(m.resolve(None, "Someone Else"))
        self.assertIsNone(m.resolve(None, None))

    def test_defaults_without_config(self):
        m = Members.from_env({})
        self.assertEqual([x.key for x in m.members], ["m1", "m2"])
        self.assertIsNone(m.resolve(ALEX_ID, "Alex Example"))

    def test_several_ids(self):
        m = Members.from_env({**ENV, "MEMBER_1_TELEGRAM_ID": f"{ALEX_ID}, 3003"})
        self.assertEqual(m.by_user_id(3003).key, "alex")


if __name__ == "__main__":
    unittest.main()
