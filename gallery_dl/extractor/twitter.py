# -*- coding: utf-8 -*-

# Copyright 2016-2020 Mike Fährmann
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Extractors for https://twitter.com/"""

from .common import Extractor, Message
from .. import text, util, exception
from ..cache import cache
import json

BASE_PATTERN = (
    r"(?:https?://)?(?:www\.|mobile\.)?"
    r"(?:twitter\.com|nitter\.net)"
)


class TwitterExtractor(Extractor):
    """Base class for twitter extractors"""
    category = "twitter"
    directory_fmt = ("{category}", "{user[name]}")
    filename_fmt = "{tweet_id}_{num}.{extension}"
    archive_fmt = "{tweet_id}_{retweet_id}_{num}"
    cookiedomain = ".twitter.com"
    root = "https://twitter.com"

    def __init__(self, match):
        Extractor.__init__(self, match)
        self.user = match.group(1)
        self.retweets = self.config("retweets", True)
        self.replies = self.config("replies", True)
        self.twitpic = self.config("twitpic", False)
        self.quoted = self.config("quoted", True)
        self.videos = self.config("videos", True)
        self.cards = self.config("cards", False)
        self._user_cache = {}

    def items(self):
        self.login()
        metadata = self.metadata()
        yield Message.Version, 1

        for tweet in self.tweets():

            if not self.retweets and "retweeted_status_id_str" in tweet:
                self.log.debug("Skipping %s (retweet)", tweet["id_str"])
                continue
            if not self.replies and "in_reply_to_user_id_str" in tweet:
                self.log.debug("Skipping %s (reply)", tweet["id_str"])
                continue
            if not self.quoted and "quoted" in tweet:
                self.log.debug("Skipping %s (quoted tweet)", tweet["id_str"])
                continue

            files = []
            if "extended_entities" in tweet:
                self._extract_media(tweet, files)
            if "card" in tweet and self.cards:
                self._extract_card(tweet, files)
            if self.twitpic:
                self._extract_twitpic(tweet, files)
            if not files:
                continue

            tdata = self._transform_tweet(tweet)
            tdata.update(metadata)
            yield Message.Directory, tdata
            for tdata["num"], file in enumerate(files, 1):
                file.update(tdata)
                url = file.pop("url")
                if "extension" not in file:
                    text.nameext_from_url(url, file)
                yield Message.Url, url, file

    def _extract_media(self, tweet, files):
        for media in tweet["extended_entities"]["media"]:
            width = media["original_info"].get("width", 0)
            height = media["original_info"].get("height", 0)

            if "video_info" in media:
                if self.videos == "ytdl":
                    files.append(
                        {
                            "url": f'ytdl:{self.root}/i/web/status/{tweet["id_str"]}',
                            "width": width,
                            "height": height,
                            "extension": None,
                        }
                    )
                elif self.videos:
                    video_info = media["video_info"]
                    variant = max(
                        video_info["variants"],
                        key=lambda v: v.get("bitrate", 0),
                    )
                    files.append({
                        "url"     : variant["url"],
                        "width"   : width,
                        "height"  : height,
                        "bitrate" : variant.get("bitrate", 0),
                        "duration": video_info.get(
                            "duration_millis", 0) / 1000,
                    })
            elif "media_url_https" in media:
                url = media["media_url_https"]
                base, _, fmt = url.rpartition(".")
                base += f"?format={fmt}&name="
                files.append(
                    text.nameext_from_url(
                        url,
                        {
                            "url": f"{base}orig",
                            "width": width,
                            "height": height,
                            "_fallback": self._image_fallback(base, url),
                        },
                    )
                )
            else:
                files.append({"url": media["media_url"]})

    @staticmethod
    def _image_fallback(base, url):
        url += ":"
        yield f"{url}orig"

        for size in ("large", "medium", "small"):
            yield base + size
            yield url + size

    def _extract_card(self, tweet, files):
        card = tweet["card"]
        if card["name"] in ("summary", "summary_large_image"):
            bvals = card["binding_values"]
            for prefix in ("photo_image_full_size_",
                           "summary_photo_image_",
                           "thumbnail_image_"):
                for size in ("original", "x_large", "large", "small"):
                    key = prefix + size
                    if key in bvals:
                        files.append(bvals[key]["image_value"])
                        return
        else:
            url = f'ytdl:{self.root}/i/web/status/{tweet["id_str"]}'
            files.append({"url": url})

    def _extract_twitpic(self, tweet, files):
        for url in tweet["entities"].get("urls", ()):
            url = url["expanded_url"]
            if "//twitpic.com/" in url and "/photos/" not in url:
                response = self.request(url, fatal=False)
                if response.status_code >= 400:
                    continue
                if url := text.extract(
                    response.text, 'name="twitter:image" value="', '"'
                )[0]:
                    files.append({"url": url})

    def _transform_tweet(self, tweet):
        entities = tweet["entities"]
        tdata = {
            "tweet_id"      : text.parse_int(tweet["id_str"]),
            "retweet_id"    : text.parse_int(
                tweet.get("retweeted_status_id_str")),
            "quote_id"      : text.parse_int(
                tweet.get("quoted_status_id_str")),
            "reply_id"      : text.parse_int(
                tweet.get("in_reply_to_status_id_str")),
            "date"          : text.parse_datetime(
                tweet["created_at"], "%a %b %d %H:%M:%S %z %Y"),
            "user"          : self._transform_user(tweet["user"]),
            "lang"          : tweet["lang"],
            "content"       : tweet["full_text"],
            "favorite_count": tweet["favorite_count"],
            "quote_count"   : tweet["quote_count"],
            "reply_count"   : tweet["reply_count"],
            "retweet_count" : tweet["retweet_count"],
        }

        if hashtags := entities.get("hashtags"):
            tdata["hashtags"] = [t["text"] for t in hashtags]

        if mentions := entities.get("user_mentions"):
            tdata["mentions"] = [{
                "id": text.parse_int(u["id_str"]),
                "name": u["screen_name"],
                "nick": u["name"],
            } for u in mentions]

        if "in_reply_to_screen_name" in tweet:
            tdata["reply_to"] = tweet["in_reply_to_screen_name"]

        if "author" in tweet:
            tdata["author"] = self._transform_user(tweet["author"])
        else:
            tdata["author"] = tdata["user"]

        return tdata

    def _transform_user(self, user):
        uid = user["id_str"]
        cache = self._user_cache

        if uid not in cache:
            cache[uid] = {
                "id"              : text.parse_int(uid),
                "name"            : user["screen_name"],
                "nick"            : user["name"],
                "description"     : user["description"],
                "location"        : user["location"],
                "date"            : text.parse_datetime(
                    user["created_at"], "%a %b %d %H:%M:%S %z %Y"),
                "verified"        : user.get("verified", False),
                "profile_banner"  : user.get("profile_banner_url", ""),
                "profile_image"   : user.get(
                    "profile_image_url_https", "").replace("_normal.", "."),
                "favourites_count": user["favourites_count"],
                "followers_count" : user["followers_count"],
                "friends_count"   : user["friends_count"],
                "listed_count"    : user["listed_count"],
                "media_count"     : user["media_count"],
                "statuses_count"  : user["statuses_count"],
            }
        return cache[uid]

    def metadata(self):
        """Return general metadata"""
        return {}

    def tweets(self):
        """Yield all relevant tweet objects"""

    def login(self):
        username, password = self._get_auth_info()
        if username:
            self._update_cookies(self._login_impl(username, password))

    @cache(maxage=360*24*3600, keyarg=1)
    def _login_impl(self, username, password):
        self.log.info("Logging in as %s", username)

        token = util.generate_csrf_token()
        self.session.cookies.clear()
        self.request(f"{self.root}/login")

        url = f"{self.root}/sessions"
        cookies = {
            "_mb_tk": token,
        }
        data = {
            "redirect_after_login"      : "/",
            "remember_me"               : "1",
            "authenticity_token"        : token,
            "wfa"                       : "1",
            "ui_metrics"                : "{}",
            "session[username_or_email]": username,
            "session[password]"         : password,
        }
        response = self.request(
            url, method="POST", cookies=cookies, data=data)

        cookies = {
            cookie.name: cookie.value
            for cookie in self.session.cookies
        }

        if "/error" in response.url or "auth_token" not in cookies:
            raise exception.AuthenticationError()
        return cookies


class TwitterTimelineExtractor(TwitterExtractor):
    """Extractor for all images from a user's timeline"""
    subcategory = "timeline"
    pattern = BASE_PATTERN + \
        r"/(?!search)(?:([^/?#]+)/?(?:$|[?#])|intent/user\?user_id=(\d+))"
    test = (
        ("https://twitter.com/supernaturepics", {
            "range": "1-40",
            "url": "c570ac1aae38ed1463be726cc46f31cac3d82a40",
        }),
        ("https://mobile.twitter.com/supernaturepics?p=i"),
        ("https://www.twitter.com/id:2976459548"),
        ("https://twitter.com/intent/user?user_id=2976459548"),
    )

    def __init__(self, match):
        TwitterExtractor.__init__(self, match)
        if uid := match.group(2):
            self.user = f"id:{uid}"

    def tweets(self):
        return TwitterAPI(self).timeline_profile(self.user)


class TwitterMediaExtractor(TwitterExtractor):
    """Extractor for all images from a user's Media Tweets"""
    subcategory = "media"
    pattern = BASE_PATTERN + r"/(?!search)([^/?#]+)/media(?!\w)"
    test = (
        ("https://twitter.com/supernaturepics/media", {
            "range": "1-40",
            "url": "c570ac1aae38ed1463be726cc46f31cac3d82a40",
        }),
        ("https://mobile.twitter.com/supernaturepics/media#t"),
        ("https://www.twitter.com/id:2976459548/media"),
    )

    def tweets(self):
        return TwitterAPI(self).timeline_media(self.user)


class TwitterLikesExtractor(TwitterExtractor):
    """Extractor for liked tweets"""
    subcategory = "likes"
    pattern = BASE_PATTERN + r"/(?!search)([^/?#]+)/likes(?!\w)"
    test = ("https://twitter.com/supernaturepics/likes",)

    def tweets(self):
        return TwitterAPI(self).timeline_favorites(self.user)


class TwitterBookmarkExtractor(TwitterExtractor):
    """Extractor for bookmarked tweets"""
    subcategory = "bookmark"
    pattern = BASE_PATTERN + r"/i/bookmarks()"
    test = ("https://twitter.com/i/bookmarks",)

    def tweets(self):
        return TwitterAPI(self).timeline_bookmark()


class TwitterListExtractor(TwitterExtractor):
    """Extractor for Twitter lists"""
    subcategory = "list"
    pattern = BASE_PATTERN + r"/i/lists/(\d+)/?$"
    test = ("https://twitter.com/i/lists/784214683683127296", {
        "range": "1-40",
        "count": 40,
        "archive": False,
    })

    def tweets(self):
        return TwitterAPI(self).timeline_list(self.user)


class TwitterListMembersExtractor(TwitterExtractor):
    """Extractor for members of a Twitter list"""
    subcategory = "list-members"
    pattern = BASE_PATTERN + r"/i/lists/(\d+)/members"
    test = ("https://twitter.com/i/lists/784214683683127296/members",)

    def items(self):
        self.login()
        for user in TwitterAPI(self).list_members(self.user):
            user["_extractor"] = TwitterTimelineExtractor
            url = f'{self.root}/intent/user?user_id={user["rest_id"]}'
            yield Message.Queue, url, user


class TwitterSearchExtractor(TwitterExtractor):
    """Extractor for all images from a search timeline"""
    subcategory = "search"
    directory_fmt = ("{category}", "Search", "{search}")
    pattern = BASE_PATTERN + r"/search/?\?(?:[^&#]+&)*q=([^&#]+)"
    test = ("https://twitter.com/search?q=nature", {
        "range": "1-40",
        "count": 40,
        "archive": False,
    })

    def metadata(self):
        return {"search": text.unquote(self.user)}

    def tweets(self):
        return TwitterAPI(self).search(text.unquote(self.user))


class TwitterTweetExtractor(TwitterExtractor):
    """Extractor for images from individual tweets"""
    subcategory = "tweet"
    pattern = BASE_PATTERN + r"/([^/?#]+|i/web)/status/(\d+)"
    test = (
        ("https://twitter.com/supernaturepics/status/604341487988576256", {
            "url": "88a40f7d25529c2501c46f2218f9e0de9aa634b4",
            "content": "ab05e1d8d21f8d43496df284d31e8b362cd3bcab",
        }),
        # 4 images
        ("https://twitter.com/perrypumas/status/894001459754180609", {
            "url": "3a2a43dc5fb79dd5432c701d8e55e87c4e551f47",
        }),
        # video
        ("https://twitter.com/perrypumas/status/1065692031626829824", {
            "pattern": r"https://video.twimg.com/ext_tw_video/.+\.mp4\?tag=5",
        }),
        # content with emoji, newlines, hashtags (#338)
        ("https://twitter.com/playpokemon/status/1263832915173048321", {
            "keyword": {"content": (
                r"re:Gear up for #PokemonSwordShieldEX with special Mystery "
                "Gifts! \n\nYou’ll be able to receive four Galarian form "
                "Pokémon with Hidden Abilities, plus some very useful items. "
                "It’s our \\(Mystery\\) Gift to you, Trainers! \n\n❓🎁➡️ "
            )},
        }),
        # Reply to deleted tweet (#403, #838)
        ("https://twitter.com/i/web/status/1170041925560258560", {
            "pattern": r"https://pbs.twimg.com/media/EDzS7VrU0AAFL4_",
        }),
        # 'replies' option (#705)
        ("https://twitter.com/i/web/status/1170041925560258560", {
            "options": (("replies", False),),
            "count": 0,
        }),
        # quoted tweet (#526, #854)
        ("https://twitter.com/StobiesGalaxy/status/1270755918330896395", {
            "pattern": r"https://pbs\.twimg\.com/media/Ea[KG].+=jpg",
            "count": 8,
        }),
        # "quoted" option (#854)
        ("https://twitter.com/StobiesGalaxy/status/1270755918330896395", {
            "options": (("quoted", False),),
            "pattern": r"https://pbs\.twimg\.com/media/EaK.+=jpg",
            "count": 4,
        }),
        # TwitPic embeds (#579)
        ("https://twitter.com/i/web/status/112900228289540096", {
            "options": (("twitpic", True),),
            "pattern": r"https://\w+.cloudfront.net/photos/large/\d+.jpg",
            "count": 3,
        }),
        # Nitter tweet (#890)
        ("https://nitter.net/ed1conf/status/1163841619336007680", {
            "url": "4a9ea898b14d3c112f98562d0df75c9785e239d9",
            "content": "f29501e44d88437fe460f5c927b7543fda0f6e34",
        }),
        # Twitter card (#1005)
        ("https://twitter.com/billboard/status/1306599586602135555", {
            "options": (("cards", True),),
            "pattern": r"https://pbs.twimg.com/card_img/\d+/",
        }),
        # original retweets (#1026)
        ("https://twitter.com/jessica_3978/status/1296304589591810048", {
            "options": (("retweets", "original"),),
            "count": 2,
            "keyword": {
                "tweet_id": 1296296016002547713,
                "date"    : "dt:2020-08-20 04:00:28",
            },
        }),
    )

    def __init__(self, match):
        TwitterExtractor.__init__(self, match)
        self.tweet_id = match.group(2)

    def tweets(self):
        return TwitterAPI(self).tweet(self.tweet_id)


class TwitterAPI():

    def __init__(self, extractor):
        self.extractor = extractor

        self.root = "https://twitter.com/i/api"
        self.headers = {
            "authorization": "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejR"
                             "COuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu"
                             "4FA33AGWWjCpTnA",
            "x-guest-token": None,
            "x-twitter-auth-type": None,
            "x-twitter-client-language": "en",
            "x-twitter-active-user": "yes",
            "x-csrf-token": None,
            "Referer": "https://twitter.com/",
        }
        self.params = {
            "include_profile_interstitial_type": "1",
            "include_blocking": "1",
            "include_blocked_by": "1",
            "include_followed_by": "1",
            "include_want_retweets": "1",
            "include_mute_edge": "1",
            "include_can_dm": "1",
            "include_can_media_tag": "1",
            "skip_status": "1",
            "cards_platform": "Web-12",
            "include_cards": "1",
            "include_ext_alt_text": "true",
            "include_quote_count": "true",
            "include_reply_count": "1",
            "tweet_mode": "extended",
            "include_entities": "true",
            "include_user_entities": "true",
            "include_ext_media_color": "true",
            "include_ext_media_availability": "true",
            "send_error_codes": "true",
            "simple_quoted_tweet": "true",
            "count": "100",
            "cursor": None,
            "ext": "mediaStats,highlightedLabel",
        }

        cookies = self.extractor.session.cookies
        cookiedomain = ".twitter.com"

        # CSRF
        csrf_token = cookies.get("ct0", domain=cookiedomain)
        if not csrf_token:
            csrf_token = util.generate_csrf_token()
            cookies.set("ct0", csrf_token, domain=cookiedomain)
        self.headers["x-csrf-token"] = csrf_token

        if cookies.get("auth_token", domain=cookiedomain):
            # logged in
            self.headers["x-twitter-auth-type"] = "OAuth2Session"
        else:
            # guest
            guest_token = self._guest_token()
            cookies.set("gt", guest_token, domain=cookiedomain)
            self.headers["x-guest-token"] = guest_token

    def tweet(self, tweet_id):
        endpoint = f"/2/timeline/conversation/{tweet_id}.json"
        tweets = []
        for tweet in self._pagination(endpoint):
            if tweet["id_str"] == tweet_id or \
                        tweet.get("_retweet_id_str") == tweet_id:
                tweets.append(tweet)
                if "quoted_status_id_str" in tweet:
                    tweet_id = tweet["quoted_status_id_str"]
                else:
                    break
        return tweets

    def timeline_profile(self, screen_name):
        user_id = self._user_id_by_screen_name(screen_name)
        endpoint = f"/2/timeline/profile/{user_id}.json"
        params = self.params.copy()
        params["include_tweet_replies"] = "false"
        return self._pagination(endpoint, params)

    def timeline_media(self, screen_name):
        user_id = self._user_id_by_screen_name(screen_name)
        endpoint = f"/2/timeline/media/{user_id}.json"
        return self._pagination(endpoint)

    def timeline_favorites(self, screen_name):
        user_id = self._user_id_by_screen_name(screen_name)
        endpoint = f"/2/timeline/favorites/{user_id}.json"
        params = self.params.copy()
        params["sorted_by_time"] = "true"
        return self._pagination(endpoint)

    def timeline_bookmark(self):
        endpoint = "/2/timeline/bookmark.json"
        return self._pagination(endpoint)

    def timeline_list(self, list_id):
        endpoint = "/2/timeline/list.json"
        params = self.params.copy()
        params["list_id"] = list_id
        params["ranking_mode"] = "reverse_chronological"
        return self._pagination(endpoint, params)

    def search(self, query):
        endpoint = "/2/search/adaptive.json"
        params = self.params.copy()
        params["q"] = query
        params["tweet_search_mode"] = "live"
        params["query_source"] = "typed_query"
        params["pc"] = "1"
        params["spelling_corrections"] = "1"
        return self._pagination(endpoint, params)

    def list_members(self, list_id):
        endpoint = "/graphql/3pV4YlpljXUTFAa1jVNWQw/ListMembers"
        variables = {
            "listId": list_id,
            "count" : 20,
            "withTweetResult": False,
            "withUserResult" : False,
        }
        return self._pagination_members(endpoint, variables)

    def list_by_rest_id(self, list_id):
        endpoint = "/graphql/EhaI2uiCBJI97e28GN8WjQ/ListByRestId"
        params = {"variables": '{"listId":"' + list_id + '"'
                               ',"withUserResult":false}'}
        try:
            return self._call(endpoint, params)["data"]["list"]
        except KeyError:
            raise exception.NotFoundError("list")

    def user_by_screen_name(self, screen_name):
        endpoint = "/graphql/ZRnOhhXPwue_JGILb9TNug/UserByScreenName"
        params = {"variables": '{"screen_name":"' + screen_name + '"'
                               ',"withHighlightedLabel":true}'}
        try:
            return self._call(endpoint, params)["data"]["user"]
        except KeyError:
            raise exception.NotFoundError("user")

    def _user_id_by_screen_name(self, screen_name):
        if screen_name.startswith("id:"):
            return screen_name[3:]
        return self.user_by_screen_name(screen_name)["rest_id"]

    @cache(maxage=3600)
    def _guest_token(self):
        root = "https://api.twitter.com"
        endpoint = "/1.1/guest/activate.json"
        return self._call(endpoint, None, root, "POST")["guest_token"]

    def _call(self, endpoint, params, root=None, method="GET"):
        if root is None:
            root = self.root
        response = self.extractor.request(
            root + endpoint, method=method, params=params,
            headers=self.headers, fatal=None)

        if csrf_token := response.cookies.get("ct0"):
            self.headers["x-csrf-token"] = csrf_token

        if response.status_code < 400:
            return response.json()
        if response.status_code == 429:
            until = response.headers.get("x-rate-limit-reset")
            self.extractor.wait(until=until, seconds=(None if until else 60))
            return self._call(endpoint, params, method)

        try:
            msg = ", ".join(
                '"' + error["message"] + '"'
                for error in response.json()["errors"]
            )
        except Exception:
            msg = response.text
        raise exception.StopExtraction(
            "%s %s (%s)", response.status_code, response.reason, msg)

    def _pagination(self, endpoint, params=None):
        if params is None:
            params = self.params.copy()
        original_retweets = (self.extractor.retweets == "original")
        pinned_tweet = True

        while True:
            cursor = tweet = None
            data = self._call(endpoint, params)

            instr = data["timeline"]["instructions"]
            if not instr:
                return
            tweet_ids = []
            tweets = data["globalObjects"]["tweets"]
            users = data["globalObjects"]["users"]

            if pinned_tweet:
                if "pinEntry" in instr[-1]:
                    tweet_ids.append(instr[-1]["pinEntry"]["entry"]["content"]
                                     ["item"]["content"]["tweet"]["id"])
                pinned_tweet = False

            # collect tweet IDs and cursor value
            for entry in instr[0]["addEntries"]["entries"]:
                entry_startswith = entry["entryId"].startswith

                if entry_startswith(("tweet-", "sq-I-t-")):
                    tweet_ids.append(
                        entry["content"]["item"]["content"]["tweet"]["id"])

                elif entry_startswith("homeConversation-"):
                    tweet_ids.extend(
                        entry["content"]["timelineModule"]["metadata"]
                        ["conversationMetadata"]["allTweetIds"][::-1])

                elif entry_startswith(("cursor-bottom-", "sq-cursor-bottom")):
                    cursor = entry["content"]["operation"]["cursor"]
                    if not cursor.get("stopOnEmptyResponse"):
                        # keep going even if there are no tweets
                        tweet = True
                    cursor = cursor["value"]

            # process tweets
            for tweet_id in tweet_ids:
                try:
                    tweet = tweets[tweet_id]
                except KeyError:
                    self.extractor.log.debug("Skipping %s (deleted)", tweet_id)
                    continue

                if "retweeted_status_id_str" in tweet:
                    retweet = tweets.get(tweet["retweeted_status_id_str"])
                    if original_retweets:
                        if not retweet:
                            continue
                        retweet["_retweet_id_str"] = tweet["id_str"]
                        tweet = retweet
                    elif retweet:
                        tweet["author"] = users[retweet["user_id_str"]]
                tweet["user"] = users[tweet["user_id_str"]]
                yield tweet

                if "quoted_status_id_str" in tweet:
                    if quoted := tweets.get(tweet["quoted_status_id_str"]):
                        quoted["author"] = users[quoted["user_id_str"]]
                        quoted["user"] = tweet["user"]
                        quoted["quoted"] = True
                        yield quoted

            # update cursor value
            if "replaceEntry" in instr[-1] :
                cursor = (instr[-1]["replaceEntry"]["entry"]
                          ["content"]["operation"]["cursor"]["value"])

            if not cursor or not tweet:
                return
            params["cursor"] = cursor

    def _pagination_members(self, endpoint, variables):
        while True:
            cursor = entry = stop = None
            params = {"variables": json.dumps(variables)}
            data = self._call(endpoint, params)

            try:
                instructions = (data["data"]["list"]["members_timeline"]
                                ["timeline"]["instructions"])
            except KeyError:
                raise exception.AuthorizationError()

            for instr in instructions:
                if instr["type"] == "TimelineAddEntries":
                    for entry in instr["entries"]:
                        if entry["entryId"].startswith("user-"):
                            yield entry["content"]["itemContent"]["user"]
                        elif entry["entryId"].startswith("cursor-bottom-"):
                            cursor = entry["content"]["value"]
                elif instr["type"] == "TimelineTerminateTimeline":
                    if instr["direction"] == "Bottom":
                        stop = True

            if stop or not cursor or not entry:
                return
            variables["cursor"] = cursor
