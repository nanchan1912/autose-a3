"""Hidden acceptance tests for issue I3 (WikiLink labels). Reused from A2 task T2."""
import unittest

import markdown
from markdown.extensions.wikilinks import WikiLinkExtension


class TestI3Hidden(unittest.TestCase):

    def test_label_used_as_text_target_used_for_url(self):
        html = markdown.markdown('See [[Some Page|the label, v2]] now.', extensions=['wikilinks'])
        self.assertEqual(
            html,
            '<p>See <a class="wikilink" href="/Some_Page/">the label, v2</a> now.</p>'
        )

    def test_config_and_build_url_receive_target(self):
        seen = []

        def my_url(label, base, end):
            seen.append(label)
            return '{}{}{}'.format(base, label.lower().replace(' ', '-'), end)

        html = markdown.markdown(
            '[[Some Page|Click here]]',
            extensions=[WikiLinkExtension(base_url='/wiki/', end_url='.html',
                                          html_class='wl', build_url=my_url)]
        )
        self.assertEqual(seen, ['Some Page'])
        self.assertEqual(html, '<p><a class="wl" href="/wiki/some-page.html">Click here</a></p>')

    def test_meta_overrides_still_apply(self):
        src = 'wiki_base_url: http://example.com/\nwiki_html_class: meta\n\n[[Home Page|Go home]]'
        html = markdown.markdown(src, extensions=['meta', 'wikilinks'])
        self.assertEqual(
            html,
            '<p><a class="meta" href="http://example.com/Home_Page/">Go home</a></p>'
        )

    def test_blank_label_falls_back_to_target(self):
        html = markdown.markdown('[[Some Page|  ]] and [[Other|]]', extensions=['wikilinks'])
        self.assertEqual(
            html,
            '<p><a class="wikilink" href="/Some_Page/">Some Page</a> and '
            '<a class="wikilink" href="/Other/">Other</a></p>'
        )


if __name__ == '__main__':
    unittest.main()
