# -*- coding: utf-8 -*-

# Copyright 2019-2020 Mike Fährmann
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Extractors for https://nozomi.la/"""

from .common import Extractor, Message
from .. import text


def decode_nozomi(n):
    for i in range(0, len(n), 4):
        yield (n[i] << 24) + (n[i+1] << 16) + (n[i+2] << 8) + n[i+3]


class NozomiExtractor(Extractor):
    """Base class for nozomi extractors"""
    category = "nozomi"
    root = "https://nozomi.la"
    filename_fmt = "{postid} {dataid}.{extension}"
    archive_fmt = "{dataid}"

    def items(self):
        yield Message.Version, 1

        data = self.metadata()
        self.session.headers["Origin"] = self.root
        self.session.headers["Referer"] = f"{self.root}/"

        for post_id in map(str, self.posts()):
            url = f"https://j.nozomi.la/post/{post_id[-1]}/{post_id[-3:-1]}/{post_id}.json"
            response = self.request(url, fatal=False)

            if response.status_code >= 400:
                self.log.warning(
                    "Skipping post %s ('%s %s')",
                    post_id, response.status_code, response.reason)
                continue

            post = response.json()
            post["tags"] = self._list(post.get("general"))
            post["artist"] = self._list(post.get("artist"))
            post["copyright"] = self._list(post.get("copyright"))
            post["character"] = self._list(post.get("character"))

            try:
                post["date"] = text.parse_datetime(
                    post["date"] + ":00", "%Y-%m-%d %H:%M:%S%z")
            except Exception:
                post["date"] = None

            post.update(data)

            images = post["imageurls"]
            for key in ("general", "imageurl", "imageurls"):
                if key in post:
                    del post[key]

            yield Message.Directory, post
            for image in images:
                post["url"] = url = text.urljoin(self.root, image["imageurl"])
                text.nameext_from_url(url, post)
                post["is_video"] = bool(image.get("is_video"))
                post["dataid"] = post["filename"]
                yield Message.Url, url, post

    def metadata(self):
        return {}

    def posts(self):
        return ()

    @staticmethod
    def _list(src):
        return [x["tagname_display"] for x in src] if src else ()


class NozomiPostExtractor(NozomiExtractor):
    """Extractor for individual posts on nozomi.la"""
    subcategory = "post"
    pattern = r"(?:https?://)?nozomi\.la/post/(\d+)"
    test = (
        ("https://nozomi.la/post/3649262.html", {
            "url": "f4522adfc8159355fd0476de28761b5be0f02068",
            "content": "cd20d2c5149871a0b80a1b0ce356526278964999",
            "keyword": {
                "artist"   : ["hammer (sunset beach)"],
                "character": ["patchouli knowledge"],
                "copyright": ["touhou"],
                "dataid"   : "re:aaa9f7c632cde1e1a5baaff3fb6a6d857ec73df7fdc5",
                "date"     : "dt:2016-07-26 02:32:03",
                "extension": "jpg",
                "favorites": int,
                "filename" : str,
                "height"   : 768,
                "is_video" : False,
                "postid"   : 3649262,
                "source"   : "danbooru",
                "sourceid" : 2434215,
                "tags"     : list,
                "type"     : "jpg",
                "url"      : str,
                "width"    : 1024,
            },
        }),
        #  multiple images per post
        ("https://nozomi.la/post/25588032.html", {
            "url": "6aa3b7db385abcc9d374bdffd19187bccbf8f228",
            "keyword": "8c3a2561ccc9ad429be9850d1383a952d0b4a8ab",
            "count": 7,
        }),
        # empty 'date' (#1163)
        ("https://nozomi.la/post/130309.html", {
            "keyword": {"date": None},
        })
    )

    def __init__(self, match):
        NozomiExtractor.__init__(self, match)
        self.post_id = match.group(1)

    def posts(self):
        return (self.post_id,)


class NozomiTagExtractor(NozomiExtractor):
    """Extractor for posts from tag searches on nozomi.la"""
    subcategory = "tag"
    directory_fmt = ("{category}", "{search_tags}")
    archive_fmt = "t_{search_tags}_{postid}"
    pattern = r"(?:https?://)?nozomi\.la/tag/([^/?#]+)-\d+\."
    test = ("https://nozomi.la/tag/3:1_aspect_ratio-1.html", {
        "pattern": r"^https://i.nozomi.la/\w/\w\w/\w+\.\w+$",
        "count": ">= 25",
        "range": "1-25",
    })

    def __init__(self, match):
        NozomiExtractor.__init__(self, match)
        self.tags = text.unquote(match.group(1)).lower()

    def metadata(self):
        return {"search_tags": self.tags}

    def posts(self):
        url = f"https://n.nozomi.la/nozomi/{self.tags}.nozomi"
        i = 0

        while True:
            headers = {"Range": f"bytes={i}-{i + 255}"}
            response = self.request(url, headers=headers)
            yield from decode_nozomi(response.content)

            i += 256
            cr = response.headers.get("Content-Range", "").rpartition("/")[2]
            if text.parse_int(cr, i) <= i:
                return


class NozomiSearchExtractor(NozomiExtractor):
    """Extractor for search results on nozomi.la"""
    subcategory = "search"
    directory_fmt = ("{category}", "{search_tags:J }")
    archive_fmt = "t_{search_tags}_{postid}"
    pattern = r"(?:https?://)?nozomi\.la/search\.html\?q=([^&#]+)"
    test = ("https://nozomi.la/search.html?q=hibiscus%203:4_ratio#1", {
        "count": ">= 5",
    })

    def __init__(self, match):
        NozomiExtractor.__init__(self, match)
        self.tags = text.unquote(match.group(1)).lower().split()

    def metadata(self):
        return {"search_tags": self.tags}

    def posts(self):
        index = None
        result = set()

        def nozomi(path):
            url = f"https://j.nozomi.la/{path}.nozomi"
            return decode_nozomi(self.request(url).content)

        for tag in self.tags:
            if tag[0] == "-":
                if not index:
                    index = set(nozomi("index"))
                items = index.difference(nozomi(f"nozomi/{tag[1:]}"))
            else:
                items = nozomi(f"nozomi/{tag}")

            if result:
                result.intersection_update(items)
            else:
                result.update(items)

        return sorted(result, reverse=True)
