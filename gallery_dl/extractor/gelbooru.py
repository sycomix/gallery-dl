# -*- coding: utf-8 -*-

# Copyright 2014-2020 Mike Fährmann
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Extractors for https://gelbooru.com/"""

from . import booru
from .. import text, exception


class GelbooruBase():
    """Base class for gelbooru extractors"""
    category = "gelbooru"
    root = "https://gelbooru.com"

    @staticmethod
    def _file_url(post):
        url = post["file_url"]
        if url.startswith(("https://mp4.gelbooru.com/", "https://video-cdn")):
            md5 = post["md5"]
            url = f"https://img2.gelbooru.com/images/{md5[:2]}/{md5[2:4]}/{md5}.webm"
        return url


class GelbooruTagExtractor(GelbooruBase, booru.BooruTagExtractor):
    """Extractor for images from gelbooru.com based on search-tags"""
    pattern = (r"(?:https?://)?(?:www\.)?gelbooru\.com/(?:index\.php)?"
               r"\?page=post&s=list&tags=(?P<tags>[^&#]+)")
    test = (
        ("https://gelbooru.com/index.php?page=post&s=list&tags=bonocho", {
            "count": 5,
        }),
        ("https://gelbooru.com/index.php?page=post&s=list&tags=bonocho", {
            "options": (("api", False),),
            "count": 5,
        }),
    )


class GelbooruPoolExtractor(GelbooruBase, booru.BooruPoolExtractor):
    """Extractor for image-pools from gelbooru.com"""
    pattern = (r"(?:https?://)?(?:www\.)?gelbooru\.com/(?:index\.php)?"
               r"\?page=pool&s=show&id=(?P<pool>\d+)")
    test = (
        ("https://gelbooru.com/index.php?page=pool&s=show&id=761", {
            "count": 6,
        }),
        ("https://gelbooru.com/index.php?page=pool&s=show&id=761", {
            "options": (("api", False),),
            "count": 6,
        }),
    )

    def metadata(self):
        url = f"{self.root}/index.php?page=pool&s=show&id={self.pool_id}"
        page = self.request(url).text

        name, pos = text.extract(page, "<h3>Now Viewing: ", "</h3>")
        if not name:
            raise exception.NotFoundError("pool")
        self.post_ids = text.extract_iter(page, 'class="" id="p', '"', pos)

        return {
            "pool": text.parse_int(self.pool_id),
            "pool_name": text.unescape(name),
        }


class GelbooruPostExtractor(GelbooruBase, booru.BooruPostExtractor):
    """Extractor for single images from gelbooru.com"""
    pattern = (r"(?:https?://)?(?:www\.)?gelbooru\.com/(?:index\.php)?"
               r"\?page=post&s=view&id=(?P<post>\d+)")
    test = ("https://gelbooru.com/index.php?page=post&s=view&id=313638", {
        "content": "5e255713cbf0a8e0801dc423563c34d896bb9229",
        "count": 1,
    })
