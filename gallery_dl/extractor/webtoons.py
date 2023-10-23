# -*- coding: utf-8 -*-

# Copyright 2020 Leonardo Taccari
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Extract images from https://www.webtoons.com/"""

from .common import Extractor, Message
from .. import exception, text, util

BASE_PATTERN = r"(?:https?://)?(?:www\.)?webtoons\.com/((en|fr)"


class WebtoonsExtractor(Extractor):
    category = "webtoons"
    root = "https://www.webtoons.com"
    cookiedomain = "www.webtoons.com"

    def __init__(self, match):
        Extractor.__init__(self, match)
        self.path, self.lang, self.genre , self.comic, self.query = \
            match.groups()
        cookies = self.session.cookies
        cookies.set("pagGDPR", "true", domain=self.cookiedomain)
        cookies.set("ageGatePass", "true", domain=self.cookiedomain)

    def request(self, url, **kwargs):
        response = Extractor.request(self, url, **kwargs)
        if response.history and "/ageGate" in response.request.url:
            raise exception.StopExtraction(
                "Redirected to age gate check ('%s')", response.request.url)
        return response


class WebtoonsEpisodeExtractor(WebtoonsExtractor):
    """Extractor for an episode on webtoons.com"""
    subcategory = "episode"
    directory_fmt = ("{category}", "{comic}")
    filename_fmt = "{episode}-{num:>02}.{extension}"
    archive_fmt = "{title_no}_{episode}_{num}"
    pattern = (BASE_PATTERN + r"/([^/?#]+)/([^/?#]+)/(?:[^/?#]+))"
               r"/viewer(?:\?([^#'\"]+))")
    test = (
        (("https://www.webtoons.com/en/comedy/safely-endangered"
          "/ep-572-earth/viewer?title_no=352&episode_no=572"), {
            "url": "11041d71a3f92728305c11a228e77cf0f7aa02ef",
            "content": "1ce950324f14018b691c42b0ede57fa25618abeb",
            "count": 5,
        }),
    )

    def __init__(self, match):
        WebtoonsExtractor.__init__(self, match)
        query = text.parse_query(self.query)
        self.title_no = query.get("title_no")
        if not self.title_no:
            raise exception.NotFoundError("title_no")
        self.episode = query.get("episode_no")
        if not self.episode:
            raise exception.NotFoundError("episode_no")

    def items(self):
        url = f"{self.root}/{self.path}/viewer?{self.query}"
        self.session.headers["Referer"] = url

        page = self.request(url).text
        data = self.get_job_metadata(page)
        imgs = self.get_image_urls(page)
        data["count"] = len(imgs)

        yield Message.Version, 1
        yield Message.Directory, data
        for data["num"], url in enumerate(imgs, 1):
            yield Message.Url, url, text.nameext_from_url(url, data)

    def get_job_metadata(self, page):
        """Collect metadata for extractor-job"""
        title, pos = text.extract(
            page, '<meta property="og:title" content="', '"')
        descr, pos = text.extract(
            page, '<meta property="og:description" content="', '"', pos)

        return {
            "genre": self.genre,
            "comic": self.comic,
            "title_no": self.title_no,
            "episode": self.episode,
            "title": text.unescape(title),
            "description": text.unescape(descr),
            "lang": self.lang,
            "language": util.code_to_language(self.lang),
        }

    @staticmethod
    def get_image_urls(page):
        """Extract and return a list of all image urls"""
        return list(text.extract_iter(page, 'class="_images" data-url="', '"'))


class WebtoonsComicExtractor(WebtoonsExtractor):
    """Extractor for an entire comic on webtoons.com"""
    subcategory = "comic"
    categorytransfer = True
    pattern = (BASE_PATTERN + r"/([^/?#]+)/([^/?#]+))"
               r"/list(?:\?([^#]+))")
    test = (
        # english
        (("https://www.webtoons.com/en/comedy/live-with-yourself/"
          "list?title_no=919"), {
            "pattern": WebtoonsEpisodeExtractor.pattern,
            "range": "1-15",
            "count": ">= 15",
        }),
        # french
        (("https://www.webtoons.com/fr/romance/subzero/"
          "list?title_no=1845&page=3"), {
            "count": ">= 15",
        }),
        # (#820)
        (("https://www.webtoons.com/en/challenge/scoob-and-shag/"
          "list?title_no=210827&page=9"), {
            "count": ">= 18",
        }),
    )

    def __init__(self, match):
        WebtoonsExtractor.__init__(self, match)
        query = text.parse_query(self.query)
        self.title_no = query.get("title_no")
        if not self.title_no:
            raise exception.NotFoundError("title_no")
        self.page_no = int(query.get("page", 1))

    def items(self):
        page = None
        data = {"_extractor": WebtoonsEpisodeExtractor}

        while True:
            path = f"/{self.path}/list?title_no={self.title_no}&page={self.page_no}"

            if page and path not in page:
                return

            page = self.request(self.root + path).text
            data["page"] = self.page_no

            for url in self.get_episode_urls(page):
                yield Message.Queue, url, data

            self.page_no += 1

    @staticmethod
    def get_episode_urls(page):
        """Extract and return all episode urls in 'page'"""
        page = text.extract(page, 'id="_listUl"', '</ul>')[0]
        return [
            match.group(0)
            for match in WebtoonsEpisodeExtractor.pattern.finditer(page)
        ]
