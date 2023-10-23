# -*- coding: utf-8 -*-

# Copyright 2018-2019 Mike Fährmann
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Extract images from https://www.myportfolio.com/"""

from .common import Extractor, Message
from .. import text, exception


class MyportfolioGalleryExtractor(Extractor):
    """Extractor for an image gallery on www.myportfolio.com"""
    category = "myportfolio"
    subcategory = "gallery"
    directory_fmt = ("{category}", "{user}", "{title}")
    filename_fmt = "{num:>02}.{extension}"
    archive_fmt = "{user}_{filename}"
    pattern = (r"(?:myportfolio:(?:https?://)?([^/]+)|"
               r"(?:https?://)?([^.]+\.myportfolio\.com))"
               r"(/[^/?#]+)?")
    test = (
        ("https://andrewling.myportfolio.com/volvo-xc-90-hybrid", {
            "url": "acea0690c76db0e5cf267648cefd86e921bc3499",
            "keyword": "6ac6befe2ee0af921d24cf1dd4a4ed71be06db6d",
        }),
        ("https://andrewling.myportfolio.com/", {
            "pattern": r"https://andrewling\.myportfolio\.com/[^/?#+]+$",
            "count": ">= 6",
        }),
        ("https://stevenilousphotography.myportfolio.com/society", {
            "exception": exception.NotFoundError,
        }),
        # custom domain
        ("myportfolio:https://tooco.com.ar/6-of-diamonds-paradise-bird", {
            "count": 3,
        }),
        ("myportfolio:https://tooco.com.ar/", {
            "pattern": pattern,
            "count": ">= 40",
        }),
    )

    def __init__(self, match):
        Extractor.__init__(self, match)
        domain1, domain2, self.path = match.groups()
        self.domain = domain1 or domain2
        self.prefix = "myportfolio:" if domain1 else ""

    def items(self):
        yield Message.Version, 1
        url = f"https://{self.domain}" + (self.path or "")
        page = self.request(url).text

        if projects := text.extract(
            page, '<section class="project-covers', '</section>'
        )[0]:
            data = {"_extractor": MyportfolioGalleryExtractor}
            base = f"{self.prefix}https://{self.domain}"
            for path in text.extract_iter(projects, ' href="', '"'):
                yield Message.Queue, base + path, data
        else:
            data = self.metadata(page)
            imgs = self.images(page)
            data["count"] = len(imgs)
            yield Message.Directory, data
            for data["num"], url in enumerate(imgs, 1):
                yield Message.Url, url, text.nameext_from_url(url, data)

    @staticmethod
    def metadata(page):
        """Collect general image metadata"""
        # og:title contains data as "<user> - <title>", but both
        # <user> and <title> can contain a "-" as well, so we get the title
        # from somewhere else and cut that amount from the og:title content

        user, pos = text.extract(
            page, 'property=og:title content="', '"')
        desc, pos = text.extract(
            page, 'property=og:description content="', '"', pos)
        title, pos = text.extract(
            page, '<h1 ', '</h1>', pos)

        if title:
            title = title.partition(">")[2]
            user = user[:-len(title)-3]
        elif user:
            user, _, title = user.partition(" - ")
        else:
            raise exception.NotFoundError()

        return {
            "user": text.unescape(user),
            "title": text.unescape(title),
            "description": text.unescape(desc or ""),
        }

    @staticmethod
    def images(page):
        """Extract and return a list of all image-urls"""
        return list(text.extract_iter(page, 'js-lightbox" data-src="', '"'))
