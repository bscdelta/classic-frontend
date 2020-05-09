import json
from os import listdir, path
import sys

import requests
import yaml

TOKEN_KEYS_MAPPING = {
    "addr": "addr",
    "symbol": "name",
    "name": "fullName",
    "decimals": "decimals"
}


def __make_listing_entry(defn):
    token = {
        dst_key: defn[src_key]
        for (src_key, dst_key) in TOKEN_KEYS_MAPPING.items()
    }
    if "__FORKDELTA_CUSTOM_SYMBOL" in defn:
        token["name"] = defn["__FORKDELTA_CUSTOM_SYMBOL"]
    return token


NOTICE_HTML_TEMPLATE = """<p class="alert alert-warning">
{notice}
</p>
"""

GUIDE_HTML_TEMPLATE = """{notice_html}<blockquote>
  <p>{description_html}</p>
  <footer>{website_href}</footer>
</blockquote>\n"""
DESCRIPTION_HTML_JOINER = "</p>\n  <p>"  # With spaces to keep indentation consistent
WEBSITE_HREF_TEMPLATE = '<a href="{url}" target="_blank">{url}</a>'


def make_description_html(defn):
    description = defn.get("description", "")
    description_html = "</p>\n  <p>".join(description.split("\n"))

    website = dict([(key, d[key]) for d in defn["links"] for key in d]).get(
        "Website", "")
    if website:
        website_href = WEBSITE_HREF_TEMPLATE.format(url=website)
    else:
        website_href = ""

    if not description_html and not website_href:
        return ""  # No guide to write

    if "notice" in defn:
        notice_html = NOTICE_HTML_TEMPLATE.format(notice=defn["notice"])
    else:
        notice_html = ""

    return GUIDE_HTML_TEMPLATE.format(
        description_html=description_html,
        website_href=website_href,
        notice_html=notice_html)


def inject_tokens(config_filename, tokens):
    with open(config_filename) as f:
        config = f.readlines()

    config_iterator = iter(config)
    prefix = []
    for line in config_iterator:
        if line == '  "tokens": [\n':
            prefix.append(line)
            break
        prefix.append(line)

    suffix = []
    suffix_started = False
    for line in config_iterator:
        if line == '  ],\n':
            suffix_started = True
        if suffix_started:
            suffix.append(line)

    json_tokens = [  # Keep the silly format, you filthy animals
        json.dumps(token_entry).replace('{', '{ ').replace('}', ' }')
        for token_entry in tokens
    ]
    formatted_tokens = [
        "    {},\n".format(json_token) for json_token in json_tokens
    ]
    formatted_tokens[-1] = formatted_tokens[-1].rstrip("\n,") + "\n"

    return prefix + formatted_tokens + suffix


CMC_ETHTOKEN_DB = "https://forkdelta.github.io/coinmarketcap-ethtoken-db/tokens/bundle.json"
CONFIG_FILE = "config/main.json"
ETH_TOKEN = {
    "addr": "0x0000000000000000000000000000000000000000",
    "name": "ETH",
    "decimals": 18
}

from web3 import Web3, HTTPProvider
from web3.exceptions import BadFunctionCallOutput
from os.path import dirname, join
with open(join(dirname(__file__), "./erc20.abi.json")) as erc20_abi_f:
    ERC20_ABI = json.load(erc20_abi_f)

web3 = Web3(HTTPProvider("https://cloudflare-eth.com"))

def get_decimals(address):
    global web3
    contract = web3.eth.contract(address, abi=ERC20_ABI)
    try:
        contract_decimals = contract.functions.decimals().call()
    except BadFunctionCallOutput as exception:
        try:
            # Try `DECIMALS` as a backup
            contract_decimals = contract.functions.DECIMALS().call()
        except BadFunctionCallOutput:
            raise exception  # Raise original: we're here because `decimals` is not defined
    return int(contract_decimals)

def main():
    from itertools import groupby
    tokens = [token for token in requests.get(CMC_ETHTOKEN_DB).json()
                if token["status"] not in ["delisted", "deprecated"]]
    outs = []

    fmt_symbol = lambda d: "CMC:{}".format(d["symbol"])
    fmt_symbol_with_id = lambda d: "CMC:{}{}".format(d["symbol"], d["id"])

    keyfunc = lambda d: d["symbol"]
    for symbol, grouper in groupby(sorted(tokens, key=keyfunc), key=keyfunc):
        for (idx, entry) in enumerate(sorted(grouper, key=lambda d: d["id"])):
            make_symbol = fmt_symbol if idx == 0 else fmt_symbol_with_id
            try:
                decimals = get_decimals(entry["address"])
            except:
                decimals = None

            outs.append({
                "addr": entry["address"].lower(),
                "name": make_symbol(entry),
                "fullName": entry["name"],
                "decimals": decimals
            })

    new_config = inject_tokens("config/main.json", outs)
    with open(CONFIG_FILE, "w", encoding="utf8") as f:
        f.writelines(new_config)



def hum(tokenbase_path):
    tokens_dir = path.join(tokenbase_path, "tokens")
    token_file_filter = lambda fname: fname.startswith("0x") and fname.endswith(".yaml")

    symbols = set("eth")
    tokens = []
    for defn_fname in sorted(
            map(lambda s: s.lower(),
                filter(token_file_filter, listdir(tokens_dir)))):
        with open(path.join(tokens_dir, defn_fname), encoding="utf8") as f:
            print(defn_fname)
            defn = yaml.safe_load(f)

        listing_entry = make_listing_entry(defn)
        if listing_entry["name"] in symbols:
            find_symbol = lambda t: t["name"] == listing_entry["name"].lower()
            previous_assignment = next(filter(find_symbol, tokens), None)
            print("ERROR: Duplicate token symbol", listing_entry["name"],
                  "({})".format(listing_entry["addr"]),
                  "previously assigned to", previous_assignment["addr"])
            exit(2)

        symbols.add(listing_entry["name"].lower())
        tokens.append(listing_entry)

        guide = make_description_html(defn)
        if guide:
            with open(
                    "tokenGuides/{}.ejs".format(listing_entry["name"]),
                    "w",
                    encoding="utf8") as f:
                f.write(guide)

    new_config = inject_tokens("config/main.json", tokens)
    with open(CONFIG_FILE, "w", encoding="utf8") as f:
        f.writelines(new_config)


if __name__ == "__main__":
    main()
