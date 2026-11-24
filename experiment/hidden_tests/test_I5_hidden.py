"""Hidden acceptance tests for issue I5 (vague: "WikiLinks don't work for a lot of my pages").

What the reporter actually meant (never written in the issue): page names that contain common
punctuation such as dots, parentheses and apostrophes are not turned into links, because the
WikiLinks pattern only accepts letters, digits, `_`, `-` and spaces.
The issue text is deliberately vague; a good requirements stage should ask what "a lot of my
pages" means instead of guessing.
"""
import unittest

import markdown


class TestI5Hidden(unittest.TestCase):

    def test_page_name_with_dot(self):
        self.assertEqual(
            markdown.markdown('See [[Node.js]].', extensions=['wikilinks']),
            '<p>See <a class="wikilink" href="/Node.js/">Node.js</a>.</p>'
        )

    def test_page_name_with_parentheses(self):
        self.assertEqual(
            markdown.markdown('[[Python (programming language)]]', extensions=['wikilinks']),
            '<p><a class="wikilink" href="/Python_(programming_language)/">Python (programming language)</a></p>'
        )

    def test_page_name_with_apostrophe(self):
        self.assertEqual(
            markdown.markdown("[[Rock 'n' Roll]]", extensions=['wikilinks']),
            "<p><a class=\"wikilink\" href=\"/Rock_'n'_Roll/\">Rock 'n' Roll</a></p>"
        )

    def test_plain_names_and_unclosed_brackets_unchanged(self):
        self.assertEqual(
            markdown.markdown('[[Some Page]] and [[not closed', extensions=['wikilinks']),
            '<p><a class="wikilink" href="/Some_Page/">Some Page</a> and [[not closed</p>'
        )


if __name__ == '__main__':
    unittest.main()
