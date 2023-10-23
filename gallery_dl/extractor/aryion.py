# -*- coding: utf-8 -*-

# Copyright 2020 Mike Fährmann
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Extractors for https://aryion.com/"""

from .common import Extractor, Message
from .. import text, util, exception
from ..cache import cache


BASE_PATTERN = r"(?:https?://)?(?:www\.)?aryion\.com/g4"


class AryionExtractor(Extractor):
    """Base class for aryion extractors"""
    category = "aryion"
    directory_fmt = ("{category}", "{user!l}", "{path:J - }")
    filename_fmt = "{id} {title}.{extension}"
    archive_fmt = "{id}"
    cookiedomain = ".aryion.com"
    cookienames = ("phpbb3_rl7a3_sid",)
    root = "https://aryion.com"

    def __init__(self, match):
        Extractor.__init__(self, match)
        self.user = match.group(1)
        self.recursive = True
        self._needle = "class='gallery-item' id='"

    def login(self):
        username, password = self._get_auth_info()
        if username:
            self._update_cookies(self._login_impl(username, password))

    @cache(maxage=14*24*3600, keyarg=1)
    def _login_impl(self, username, password):
        self.log.info("Logging in as %s", username)

        url = f"{self.root}/forum/ucp.php?mode=login"
        data = {
            "username": username,
            "password": password,
            "login": "Login",
        }

        response = self.request(url, method="POST", data=data)
        if b"You have been successfully logged in." not in response.content:
            raise exception.AuthenticationError()
        return {c: response.cookies[c] for c in self.cookienames}

    def items(self):
        self.login()

        for post_id in self.posts():
            if post := self._parse_post(post_id):
                yield Message.Directory, post
                yield Message.Url, post["url"], post
            elif post is False and self.recursive:
                base = f"{self.root}/g4/view/"
                data = {"_extractor": AryionPostExtractor}
                for post_id in self._pagination(base + post_id):
                    yield Message.Queue, base + post_id, data

    def posts(self):
        """Yield relevant post IDs"""

    def _pagination(self, url):
        while True:
            page = self.request(url).text
            yield from text.extract_iter(
                page, self._needle, "'")

            pos = page.find("Next &gt;&gt;")
            if pos < 0:
                return
            url = self.root + text.rextract(page, "href='", "'", pos)[0]

    def _parse_post(self, post_id):
        url = f"{self.root}/g4/data.php?id={post_id}"
        with self.request(url, method="HEAD", fatal=False) as response:

            if response.status_code >= 400:
                self.log.warning(
                    "Unable to fetch post %s ('%s %s')",
                    post_id, response.status_code, response.reason)
                return None
            headers = response.headers

            # folder
            if headers["content-type"] in (
                "application/x-folder",
                "application/x-comic-folder",
                "application/x-comic-folder-nomerge",
            ):
                return False

            # get filename from 'Content-Disposition' header
            cdis = headers["content-disposition"]
            fname, _, ext = text.extract(
                cdis, 'filename="', '"')[0].rpartition(".")
            if not fname:
                fname, ext = ext, fname

            # get file size from 'Content-Length' header
            clen = headers.get("content-length")

            # fix 'Last-Modified' header
            lmod = headers["last-modified"]
            if lmod[22] != ":":
                lmod = f"{lmod[:22]}:{lmod[22:24]} GMT"

        post_url = f"{self.root}/g4/view/{post_id}"
        extr = text.extract_from(self.request(post_url).text)

        title, _, artist = text.unescape(extr(
            "<title>g4 :: ", "<")).rpartition(" by ")
        data = {
            "id"    : text.parse_int(post_id),
            "url"   : url,
            "user"  : self.user or artist,
            "title" : title,
            "artist": artist,
            "path"  : text.split_html(extr("cookiecrumb'>", '</span'))[4:-1:2],
            "date"  : extr("class='pretty-date' title='", "'"),
            "size"  : text.parse_int(clen),
            "views" : text.parse_int(extr("Views</b>:", "<").replace(",", "")),
            "width" : text.parse_int(extr("Resolution</b>:", "x")),
            "height": text.parse_int(extr("", "<")),
            "comments" : text.parse_int(extr("Comments</b>:", "<")),
            "favorites": text.parse_int(extr("Favorites</b>:", "<")),
            "tags"     : text.split_html(extr("class='taglist'>", "</span>")),
            "description": text.unescape(text.remove_html(extr(
                "<p>", "</p>"), "", "")),
            "filename" : fname,
            "extension": ext,
            "_mtime"   : lmod,
        }

        d1, _, d2 = data["date"].partition(",")
        data["date"] = text.parse_datetime(
            d1[:-2] + d2, "%b %d %Y %I:%M %p", -5)

        return data


class AryionGalleryExtractor(AryionExtractor):
    """Extractor for a user's gallery on eka's portal"""
    subcategory = "gallery"
    categorytransfer = True
    pattern = BASE_PATTERN + r"/(?:gallery/|user/|latest.php\?name=)([^/?#]+)"
    test = (
        ("https://aryion.com/g4/gallery/jameshoward", {
            "options": (("recursive", False),),
            "pattern": r"https://aryion\.com/g4/data\.php\?id=\d+$",
            "range": "48-52",
            "count": 5,
        }),
        ("https://aryion.com/g4/user/jameshoward"),
        ("https://aryion.com/g4/latest.php?name=jameshoward"),
    )

    def __init__(self, match):
        AryionExtractor.__init__(self, match)
        self.recursive = self.config("recursive", True)
        self.offset = 0

    def skip(self, num):
        if self.recursive:
            num = 0
        self.offset += num
        return num

    def posts(self):
        if self.recursive:
            url = f"{self.root}/g4/gallery/{self.user}"
            return self._pagination(url)
        else:
            self._needle = "class='thumb' href='/g4/view/"
            url = f"{self.root}/g4/latest.php?name={self.user}"
            return util.advance(self._pagination(url), self.offset)


class AryionPostExtractor(AryionExtractor):
    """Extractor for individual posts on eka's portal"""
    subcategory = "post"
    pattern = BASE_PATTERN + r"/view/(\d+)"
    test = (
        ("https://aryion.com/g4/view/510079", {
            "url": "f233286fa5558c07ae500f7f2d5cb0799881450e",
            "keyword": {
                "artist"   : "jameshoward",
                "user"     : "jameshoward",
                "filename" : "jameshoward-510079-subscribestar_150",
                "extension": "jpg",
                "id"       : 510079,
                "width"    : 1665,
                "height"   : 1619,
                "size"     : 784239,
                "title"    : "I'm on subscribestar now too!",
                "description": r"re:Doesn't hurt to have a backup, right\?",
                "tags"     : ["Non-Vore", "subscribestar"],
                "date"     : "dt:2019-02-16 19:30:00",
                "path"     : [],
                "views"    : int,
                "favorites": int,
                "comments" : int,
                "_mtime"   : "Sat, 16 Feb 2019 19:30:34 GMT",
            },
        }),
        # x-folder (#694)
        ("https://aryion.com/g4/view/588928", {
            "pattern": pattern,
            "count": ">= 8",
        }),
        # x-comic-folder (#945)
        ("https://aryion.com/g4/view/537379", {
            "pattern": pattern,
            "count": 2,
        }),
    )

    def posts(self):
        post_id, self.user = self.user, None
        return (post_id,)
