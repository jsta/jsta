from python_graphql_client import GraphqlClient
import feedparser
import httpx
import json
import pathlib
import re
import os
import datetime
import json
import pandas as pd


root = pathlib.Path(__file__).parent.resolve()
client = GraphqlClient(endpoint="https://api.github.com/graphql")

## https://stackoverflow.com/a/9161531/3362993
## for local builds
# keys = {}
# with open(os.path.expanduser('~/.Renviron')) as myfile:
#     for line in myfile:
#         name, key = line.partition("=")[::2]
#         keys[name.strip()] = str.rstrip(key)
# TOKEN = keys['GITHUB_PAT']

# comment out below line for local builds
TOKEN = os.environ.get("JSTA_TOKEN", "")


def replace_chunk(content, marker, chunk, inline=False):
    r = re.compile(
        r"<!\-\- {} starts \-\->.*<!\-\- {} ends \-\->".format(marker, marker),
        re.DOTALL,
    )
    if not inline:
        chunk = "\n{}\n".format(chunk)
    chunk = "<!-- {} starts -->{}<!-- {} ends -->".format(marker, chunk, marker)
    return r.sub(chunk, content)


def make_query(after_cursor=None):
    return """
query {
  viewer {
    repositories(first: 100, ownerAffiliations:[OWNER, ORGANIZATION_MEMBER, COLLABORATOR], privacy: PUBLIC, after:AFTER) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        name
        description
        url 
        repositoryTopics (first: 20) {          
            nodes {
              topic {
                name
              }
            }
          }        
        owner {
            login
        }
        releases(last:1) {
          totalCount          
          nodes {
            name
            publishedAt
            url                        
          }
        }
      }
    }
  }
}
""".replace(
        "AFTER", '"{}"'.format(after_cursor) if after_cursor else "null"
    )


def fetch_releases(oauth_token):
    repos = []
    releases = []
    repo_names = set()
    has_next_page = True
    after_cursor = None

    while has_next_page:
        # oauth_token = TOKEN
        data = client.execute(
            query=make_query(after_cursor),
            headers={"Authorization": "Bearer {}".format(oauth_token)},
        )
        print()
        print(json.dumps(data, indent=4))
        print()
        for repo in data["data"]["viewer"]["repositories"]["nodes"]:
            # repo = data["data"]["viewer"]["repositories"]["nodes"][0]
            if repo["releases"]["totalCount"] and repo["name"] not in repo_names:
                repos.append(repo)
                repo_names.add(repo["name"])

                topics_raw = pd.io.json._normalize.nested_to_record(
                    repo["repositoryTopics"]["nodes"]
                )
                topics = []
                for topic in topics_raw:
                    topics.append(list(topic.values())[0])
                topics = ", ".join(topics)

                releases.append(
                    {
                        "repo": repo["name"],
                        "login": repo["owner"]["login"],
                        "repo_url": repo["url"],
                        "description": repo["description"],
                        "keywords": topics,
                        "release": repo["releases"]["nodes"][0]["name"]
                        .replace(repo["name"], "")
                        .strip(),
                        "published_at": repo["releases"]["nodes"][0][
                            "publishedAt"
                        ].split("T")[0],
                        "url": repo["releases"]["nodes"][0]["url"],
                    }
                )
        has_next_page = data["data"]["viewer"]["repositories"]["pageInfo"][
            "hasNextPage"
        ]
        after_cursor = data["data"]["viewer"]["repositories"]["pageInfo"]["endCursor"]
    return releases


def fetch_blog_entries():

    entries = feedparser.parse("https://jsta.rbind.io/blog/index.xml")["entries"]
    return [
        {
            "title": entry["title"],
            "url": entry["link"].split("#")[0],
            "published": datetime.datetime.strptime(
                entry["published"], "%a, %d %b %Y %H:%M:%S %z"
            ).strftime("%Y-%m-%d"),
        }
        for entry in entries
    ]


if __name__ == "__main__":
    readme = root / "README.md"
    project_releases = root / "releases.md"
    releases = fetch_releases(TOKEN)
    # remove bad releases
    releases = list(
        filter(lambda r: r["login"] not in ["ropenscilabs", "rbind"], releases)
    )
    releases = list(
        filter(
            lambda r: r["repo"]
            not in [
                "LAGOS_GIS_Toolbox",
                "LAGOSClimateSensitivity",
                "rgrass7sf",
                "tidybayes",
                "openbugs",
                "spnetwork",
                "LAGOS_NETS",
                "LivinOnTheEdge",
                "lagosus-reservoir",
                "metabolism_phenology"
            ],
            releases,
        )
    )

    # add missing releases
    releases_missing = [
        {
            "repo": "smwrQW",
            "login": "USGS-R",
            "repo_url": "https://github.com/USGS-R/smwrQW",
            "description": "Water quality USGS water science R functions.",
            "keywords": "rstats, fortran",
            "release": "0.7.13",
            "published_at": "2017-07-24",
            "url": "https://github.com/USGS-R/smwrQW/releases/tag/v0.7.13",
        }
    ]
    releases.extend(releases_missing)

    releases.sort(key=lambda r: r["published_at"], reverse=True)

    with open("releases.json", "w") as outfile:
        json.dump(releases, outfile)

    md = "\n".join(
        [
            "* [{repo} {release}]({url}) - {published_at}".format(**release)
            for release in releases[:5]
        ]
    )
    readme_contents = readme.open().read()
    rewritten = replace_chunk(readme_contents, "recent_releases", md)

    # Write out full project-releases.md file
    project_releases_md = "\n".join(
        [
            (
                "* **[{repo}]({repo_url})**: [{release}]({url}) - {published_at}\n"
                "<br>{description}"
            ).format(**release)
            for release in releases
        ]
    )
    project_releases_content = project_releases.open().read()
    project_releases_content = replace_chunk(
        project_releases_content, "recent_releases", project_releases_md
    )
    project_releases_content = replace_chunk(
        project_releases_content, "release_count", str(len(releases)), inline=True
    )
    project_releases.open("w").write(project_releases_content)

    entries = fetch_blog_entries()[:5]
    entries_md = "\n".join(
        ["* [{title}]({url}) - {published}".format(**entry) for entry in entries]
    )
    rewritten = replace_chunk(rewritten, "blog", entries_md)

    readme.open("w").write(rewritten)
