# -*- coding: utf-8 -*-

# Copyright 2016-2020 Mike Fährmann
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Collection of extractors for various imagehosts"""

from .common import Extractor, Message
from .. import text, exception
from ..cache import memcache
from os.path import splitext


class ImagehostImageExtractor(Extractor):
    """Base class for single-image extractors for various imagehosts"""
    basecategory = "imagehost"
    subcategory = "image"
    archive_fmt = "{token}"
    https = False
    method = "post"
    params = "simple"
    cookies = None
    encoding = None

    def __init__(self, match):
        Extractor.__init__(self, match)
        self.page_url = f'http{"s" if self.https else ""}://{match.group(1)}'
        self.token = match.group(2)
        if self.params == "simple":
            self.params = {
                "imgContinue": "Continue+to+image+...+",
            }
        elif self.params == "complex":
            self.params = {
                "op": "view",
                "id": self.token,
                "pre": "1",
                "adb": "1",
                "next": "Continue+to+image+...+",
            }
        else:
            self.params = {}
            self.method = "get"

    def items(self):
        page = self.request(
            self.page_url,
            method=self.method,
            data=self.params,
            cookies=self.cookies,
            encoding=self.encoding,
        ).text

        url, filename = self.get_info(page)
        data = text.nameext_from_url(filename, {"token": self.token})
        if self.https and url.startswith("http:"):
            url = f"https:{url[5:]}"

        yield Message.Version, 1
        yield Message.Directory, data
        yield Message.Url, url, data

    def get_info(self, page):
        """Find image-url and string to get filename from"""


class ImxtoImageExtractor(ImagehostImageExtractor):
    """Extractor for single images from imx.to"""
    category = "imxto"
    pattern = (r"(?:https?://)?(?:www\.)?((?:imx\.to|img\.yt)"
               r"/(?:i/|img-)(\w+)(\.html)?)")
    test = (
        ("https://imx.to/i/1qdeva", {  # new-style URL
            "url": "ab2173088a6cdef631d7a47dec4a5da1c6a00130",
            "keyword": "1153a986c939d7aed599905588f5c940048bc517",
            "content": "0c8768055e4e20e7c7259608b67799171b691140",
        }),
        ("https://imx.to/img-57a2050547b97.html", {  # old-style URL
            "url": "a83fe6ef1909a318c4d49fcf2caf62f36c3f9204",
            "keyword": "fd2240aee77a21b8252d5b829a1f7e542f927f09",
            "content": "54592f2635674c25677c6872db3709d343cdf92f",
        }),
        ("https://img.yt/img-57a2050547b97.html", {  # img.yt domain
            "url": "a83fe6ef1909a318c4d49fcf2caf62f36c3f9204",
        }),
        ("https://imx.to/img-57a2050547b98.html", {
            "exception": exception.NotFoundError,
        }),
    )
    https = True
    encoding = "utf-8"

    def __init__(self, match):
        ImagehostImageExtractor.__init__(self, match)
        if "/img-" in self.page_url:
            self.page_url = self.page_url.replace("img.yt", "imx.to")
            self.url_ext = True
        else:
            self.url_ext = False

    def get_info(self, page):
        url, pos = text.extract(
            page, '<div style="text-align:center;"><a href="', '"')
        if not url:
            raise exception.NotFoundError("image")
        filename, pos = text.extract(page, ' title="', '"', pos)
        if self.url_ext and filename:
            filename += splitext(url)[1]
        return url, filename or url


class AcidimgImageExtractor(ImagehostImageExtractor):
    """Extractor for single images from acidimg.cc"""
    category = "acidimg"
    pattern = r"(?:https?://)?((?:www\.)?acidimg\.cc/img-([a-z0-9]+)\.html)"
    test = ("https://acidimg.cc/img-5acb6b9de4640.html", {
        "url": "f132a630006e8d84f52d59555191ed82b3b64c04",
        "keyword": "a8bb9ab8b2f6844071945d31f8c6e04724051f37",
        "content": "0c8768055e4e20e7c7259608b67799171b691140",
    })
    https = True
    encoding = "utf-8"

    def get_info(self, page):
        url, pos = text.extract(page, "<img class='centred' src='", "'")
        if not url:
            raise exception.NotFoundError("image")
        filename, pos = text.extract(page, " alt='", "'", pos)
        return url, (filename + splitext(url)[1]) if filename else url


class ImagevenueImageExtractor(ImagehostImageExtractor):
    """Extractor for single images from imagevenue.com"""
    category = "imagevenue"
    pattern = (r"(?:https?://)?(img\d+\.imagevenue\.com"
               r"/img\.php\?image=(?:[a-z]+_)?(\d+)_[^&#]+)")
    test = (("http://img28116.imagevenue.com/img.php"
             "?image=th_52709_test_122_64lo.jpg"), {
        "url": "46812995d557f2c6adf0ebd0e631e6e4e45facde",
        "content": "59ec819cbd972dd9a71f25866fbfc416f2f215b3",
    })
    params = None

    def get_info(self, page):
        url = text.extract(page, "SRC='", "'")[0]
        return text.urljoin(self.page_url, url), url


class ImagetwistImageExtractor(ImagehostImageExtractor):
    """Extractor for single images from imagetwist.com"""
    category = "imagetwist"
    pattern = r"(?:https?://)?((?:www\.)?imagetwist\.com/([a-z0-9]{12}))"
    test = ("https://imagetwist.com/f1i2s4vhvbrq/test.png", {
        "url": "8d5e168c0bee30211f821c6f3b2116e419d42671",
        "keyword": "d1060a4c2e3b73b83044e20681712c0ffdd6cfef",
        "content": "0c8768055e4e20e7c7259608b67799171b691140",
    })
    https = True
    params = None

    @property
    @memcache(maxage=3*3600)
    def cookies(self):
        return self.request(self.page_url).cookies

    def get_info(self, page):
        url     , pos = text.extract(page, 'center;"><img src="', '"')
        filename, pos = text.extract(page, ' alt="', '"', pos)
        return url, filename


class ImgspiceImageExtractor(ImagehostImageExtractor):
    """Extractor for single images from imgspice.com"""
    category = "imgspice"
    pattern = r"(?:https?://)?((?:www\.)?imgspice\.com/([^/?#]+))"
    test = ("https://imgspice.com/nwfwtpyog50y/test.png.html", {
        "url": "b8c30a8f51ee1012959a4cfd46197fabf14de984",
        "keyword": "100e310a19a2fa22d87e1bbc427ecb9f6501e0c0",
        "content": "0c8768055e4e20e7c7259608b67799171b691140",
    })
    https = True
    params = None

    def get_info(self, page):
        pos = page.find('id="imgpreview"')
        if pos < 0:
            raise exception.NotFoundError("image")
        url , pos = text.extract(page, 'src="', '"', pos)
        name, pos = text.extract(page, 'alt="', '"', pos)
        return url, text.unescape(name)


class PixhostImageExtractor(ImagehostImageExtractor):
    """Extractor for single images from pixhost.to"""
    category = "pixhost"
    pattern = (r"(?:https?://)?((?:www\.)?pixhost\.(?:to|org)"
               r"/show/\d+/(\d+)_[^/?#]+)")
    test = ("http://pixhost.to/show/190/130327671_test-.png", {
        "url": "4e5470dcf6513944773044d40d883221bbc46cff",
        "keyword": "3bad6d59db42a5ebbd7842c2307e1c3ebd35e6b0",
        "content": "0c8768055e4e20e7c7259608b67799171b691140",
    })
    https = True
    params = None
    cookies = {"pixhostads": "1", "pixhosttest": "1"}

    def get_info(self, page):
        url     , pos = text.extract(page, "class=\"image-img\" src=\"", "\"")
        filename, pos = text.extract(page, "alt=\"", "\"", pos)
        return url, filename


class PostimgImageExtractor(ImagehostImageExtractor):
    """Extractor for single images from postimages.org"""
    category = "postimg"
    pattern = (r"(?:https?://)?((?:www\.)?(?:postimg|pixxxels)\.(?:cc|org)"
               r"/(?:image/)?([^/?#]+)/?)")
    test = ("https://postimg.cc/Wtn2b3hC", {
        "url": "0794cfda9b8951a8ac3aa692472484200254ab86",
        "keyword": "2d05808d04e4e83e33200db83521af06e3147a84",
        "content": "cfaa8def53ed1a575e0c665c9d6d8cf2aac7a0ee",
    })
    https = True
    params = None

    def get_info(self, page):
        url     , pos = text.extract(page, 'id="main-image" src="', '"')
        filename, pos = text.extract(page, 'class="imagename">', '<', pos)
        return url, text.unescape(filename)


class TurboimagehostImageExtractor(ImagehostImageExtractor):
    """Extractor for single images from www.turboimagehost.com"""
    category = "turboimagehost"
    pattern = (r"(?:https?://)?((?:www\.)?turboimagehost\.com"
               r"/p/(\d+)/[^/?#]+\.html)")
    test = ("https://www.turboimagehost.com/p/39078423/test--.png.html", {
        "url": "b94de43612318771ced924cb5085976f13b3b90e",
        "keyword": "704757ca8825f51cec516ec44c1e627c1f2058ca",
        "content": "0c8768055e4e20e7c7259608b67799171b691140",
    })
    https = True
    params = None

    def get_info(self, page):
        url = text.extract(page, 'src="', '"', page.index("<img "))[0]
        return url, url
