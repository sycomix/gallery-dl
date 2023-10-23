# -*- coding: utf-8 -*-

# Copyright 2021 Mike Fährmann
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Extractors for https://derpibooru.org/"""

from .booru import BooruExtractor
from .. import text, exception
import operator

BASE_PATTERN = r"(?:https?://)?derpibooru\.org"


class DerpibooruExtractor(BooruExtractor):
    """Base class for derpibooru extractors"""
    category = "derpibooru"
    filename_fmt = "{filename}.{extension}"
    archive_fmt = "{id}"
    root = "https://derpibooru.org"
    request_interval = 1.0
    per_page = 50

    _file_url = operator.itemgetter("view_url")

    @staticmethod
    def _prepare(post):
        post["date"] = text.parse_datetime(
            post["created_at"], "%Y-%m-%dT%H:%M:%S")

    @staticmethod
    def _extended_tags(post):
        pass

    def _pagination(self, url, params):
        params["page"] = 1
        params["per_page"] = self.per_page

        if api_key := self.config("api-key"):
            params["key"] = api_key

        if filter_id := self.config("filter"):
            params["filter_id"] = filter_id

        while True:
            data = self.request(url, params=params).json()
            yield from data["images"]

            if len(data["images"]) < self.per_page:
                return
            params["page"] += 1


class DerpibooruPostExtractor(DerpibooruExtractor):
    """Extractor for single posts from derpibooru.org"""
    subcategory = "post"
    pattern = BASE_PATTERN + r"/images/(\d+)"
    test = ("https://derpibooru.org/images/1", {
        "content": "88449eeb0c4fa5d3583d0b794f6bc1d70bf7f889",
        "count": 1,
        "keyword": {
            "animated": False,
            "aspect_ratio": 1.0,
            "comment_count": int,
            "created_at": "2012-01-02T03:12:33",
            "date": "dt:2012-01-02 03:12:33",
            "deletion_reason": None,
            "description": "",
            "downvotes": int,
            "duplicate_of": None,
            "duration": 0.04,
            "extension": "png",
            "faves": int,
            "first_seen_at": "2012-01-02T03:12:33",
            "format": "png",
            "height": 900,
            "hidden_from_users": False,
            "id": 1,
            "mime_type": "image/png",
            "name": "1__safe_fluttershy_solo_cloud_happy_flying_upvotes+galore"
                    "_artist-colon-speccysy_get_sunshine",
            "orig_sha512_hash": None,
            "processed": True,
            "representations": dict,
            "score": int,
            "sha512_hash": "f16c98e2848c2f1bfff3985e8f1a54375cc49f78125391aeb8"
                           "0534ce011ead14e3e452a5c4bc98a66f56bdfcd07ef7800663"
                           "b994f3f343c572da5ecc22a9660f",
            "size": 860914,
            "source_url": "https://www.deviantart.com/speccysy/art"
                          "/Afternoon-Flight-215193985",
            "spoilered": False,
            "tag_count": 36,
            "tag_ids": list,
            "tags": list,
            "thumbnails_generated": True,
            "updated_at": "2020-05-28T13:14:07",
            "uploader": "Clover the Clever",
            "uploader_id": 211188,
            "upvotes": int,
            "view_url": str,
            "width": 900,
            "wilson_score": float,
        },
    })

    def __init__(self, match):
        DerpibooruExtractor.__init__(self, match)
        self.image_id = match.group(1)

    def posts(self):
        url = f"{self.root}/api/v1/json/images/{self.image_id}"
        return (self.request(url).json()["image"],)


class DerpibooruSearchExtractor(DerpibooruExtractor):
    """Extractor for search results on derpibooru.org"""
    subcategory = "search"
    directory_fmt = ("{category}", "{search_tags}")
    pattern = BASE_PATTERN + r"/(?:search/?\?([^#]+)|tags/([^/?#]+))"
    test = (
        ("https://derpibooru.org/search?q=cute", {
            "range": "40-60",
            "count": 21,
        }),
        ("https://derpibooru.org/tags/cute", {
            "range": "40-60",
            "count": 21,
        }),
    )

    def __init__(self, match):
        DerpibooruExtractor.__init__(self, match)
        query, tags = match.groups()
        self.params = text.parse_query(query) if query else {"q": tags}

    def metadata(self):
        return {"search_tags": self.params.get("q", "")}

    def posts(self):
        url = f"{self.root}/api/v1/json/search/images"
        return self._pagination(url, self.params)


class DerpibooruGalleryExtractor(DerpibooruExtractor):
    """Extractor for galleries on derpibooru.org"""
    subcategory = "gallery"
    directory_fmt = ("{category}", "galleries",
                     "{gallery[id]} {gallery[title]}")
    pattern = BASE_PATTERN + r"/galleries/(\d+)"
    test = ("https://derpibooru.org/galleries/1", {
        "pattern": r"https://derpicdn\.net/img/view/\d+/\d+/\d+/\d+[^/]+$",
        "keyword": {
            "gallery": {
                "description": "Indexes start at 1 :P",
                "id": 1,
                "spoiler_warning": "",
                "thumbnail_id": 1,
                "title": "The Very First Gallery",
                "user": "DeliciousBlackInk",
                "user_id": 365446,
            },
        },
    })

    def __init__(self, match):
        DerpibooruExtractor.__init__(self, match)
        self.gallery_id = match.group(1)

    def metadata(self):
        url = f"{self.root}/api/v1/json/search/galleries"
        params = {"q": f"id:{self.gallery_id}"}
        if galleries := self.request(url, params=params).json()["galleries"]:
            return {"gallery": galleries[0]}
        else:
            raise exception.NotFoundError("gallery")

    def posts(self):
        gallery_id = f"gallery_id:{self.gallery_id}"
        url = f"{self.root}/api/v1/json/search/images"
        params = {"sd": "desc", "sf": gallery_id, "q" : gallery_id}
        return self._pagination(url, params)
