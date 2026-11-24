"""Read-only relevance checks: synthetic daily probes and a recent-post replay.

No article bodies are stored here. Real cases are fetched from their publishers.
These are targeted development checks, not a statistical accuracy benchmark.
"""

import infobot_v2 as bot
import bot_common as common


SELF_CASES = [
    ("public_kickbacks", "publish", "Procurement kickbacks investigated",
     "Prosecutors allege that a mayor steered public procurement contracts to a supplier in exchange for payments into her personal account. The mayor was responsible for awarding the contracts. Investigators traced the alleged kickbacks to a shell company she controlled. The inquiry concerns these payments and the manipulation of public purchasing. The mayor denies wrongdoing."),
    ("private_embezzlement", "publish", "Company treasurer accused of diverting pension assets",
     "A private company's treasurer was entrusted with managing staff pension assets. Investigators allege he secretly transferred those assets to his own investment company, concealing the transfers through false ledger entries. The case focuses on his diversion of entrusted funds for personal enrichment. He denies the allegations. No public officials are involved."),
    ("foreign_disinformation", "skip", "Volunteers teach media literacy ahead of election",
     "A foreign state circulated fabricated stories to influence an election and support friendly candidates. Volunteers are teaching residents how to verify claims and recognise impersonated news outlets. The article describes the false stories and the classes. It reports no diverted entrusted resources, bribery, corrupt appointments, self-dealing or illicit financing."),
    ("industrial_subsidies", "skip", "State bank finances expansion of wind companies",
     "A state bank financed domestic wind companies expanding abroad, following its mandate to support the government's industrial policy. Competition authorities are investigating whether state subsidies and preferential loans distorted competition. The article discusses lending volumes, manufacturing and energy security. It alleges no self-dealing, kickbacks, illicit patronage or diversion of entrusted resources."),
    ("harmful_business", "skip", "Platform profits from harmful content despite complaints",
     "A company failed to remove abusive and illegal content after complaints. Court filings allege negligent moderation and revenue earned from that content. Victims seek compensation and stronger enforcement. The article focuses on the company's moderation failures and the resulting harm. It describes no bribery, embezzlement, self-dealing or corrupt use of delegated decision-making authority."),
    ("illustrative_anecdote", "skip", "Why journalism deserves conservation funding",
     "The author opens by recalling an old case in which a mayor was convicted of accepting kickbacks on a conservation contract after journalists exposed the payments. The rest of the commentary argues for funding independent journalism, explains how reporting helps conservation projects, and discusses measuring its impact. Several other past investigations illustrate the argument. There are no new findings about the old case; the commentary primarily advocates journalism funding."),
]

REAL_CASES = [
    ("forest_mapping", "skip", "Mongabay", "It’s time to put Africa’s forest communities on the map (commentary)",
     "https://news.mongabay.com/2026/11/its-past-time-to-put-africas-forest-communities-on-the-map-commentary/"),
    ("journalism_commentary", "skip", "Mongabay", "Why conservation needs independent journalism (commentary)",
     "https://news.mongabay.com/2026/11/why-conservation-needs-independent-journalism/"),
    ("wind_financing", "skip", "ICIJ", "How banking giant ICBC helped Chinese firms gain a foothold in Europe’s wind market",
     "https://www.icij.org/investigations/china-capital/how-banking-giant-icbc-helped-chinese-firms-gain-a-foothold-in-europes-wind-market/"),
    ("platform_abuse", "skip", "ICIJ", "‘He used Pornhub as the gun’",
     "https://www.icij.org/news/2026/11/he-used-pornhub-as-the-gun/"),
    ("wildlife_bribes", "publish", "Mongabay", "Wildlife trafficking persists in West, Central Africa despite crackdowns: Report",
     "https://news.mongabay.com/2026/11/wildlife-trafficking-persists-in-west-central-africa-despite-crackdowns-report/"),
    ("pharma_corruption", "publish", "ICIJ", "Pharma giants pay millions to Russian distributor entangled in corruption allegations to win cancer drug business",
     "https://www.icij.org/investigations/cancer-calculus/pharma-giants-pay-millions-to-russian-distributor-entangled-in-corruption-allegations-to-win-cancer-drug-business/"),
    ("loanbook_corruption", "publish", "ICIJ", "Anatomy of a Chinese loanbook",
     "https://www.icij.org/investigations/china-capital/anatomy-of-a-chinese-loanbook/"),
    ("state_self_dealing", "publish", "CORRECTIV", "The State as a Private Bank Account",
     "https://correctiv.org/en/europe/2026/11/13/the-state-as-a-private-bank-account/"),
]


def self_checks(config, key):
    rows = []
    for name, expected, title, text in SELF_CASES:
        article = {"source_name": "Synthetic operational self-check", "title": title,
                   "link": "https://example.org/self-check/" + name}
        try:
            result = bot.classify_text(article, config, key, text)
        except common.SetupError as exc:
            if isinstance(exc, common.APIError) or "LLM classification" in str(exc):
                raise
            rows.append({"case": name, "expected": expected, "status": "failed", "error": str(exc)})
            continue
        rows.append({"case": name, "expected": expected, "decision": result["decision"],
                     "reason": result["reason"], "api_usage": result["api_usage"],
                     "verified": result.get("verification", {}).get("decision") == "publish",
                     "status": "passed" if result["decision"] == expected else "failed"})
        print("Self-check " + name + ": " + rows[-1]["status"], flush=True)
    return rows


def replay_recent(config, key):
    rows = []
    for name, expected, source, title, url in REAL_CASES:
        row = {"case": name, "expected": expected, "source": source, "url": url}
        try:
            feed = next(f for f in config["feeds"] if f["source_name"] == source)
            result = bot.classify({**feed, "title": title, "link": url}, config, key)
            row.update(decision=result["decision"], reason=result["reason"],
                       selection=result["selection"], verification=result.get("verification"),
                       article_input=result["article_input"], api_usage=result["api_usage"],
                       status="passed" if result["decision"] == expected else "failed")
        except common.SetupError as exc:
            if expected == "skip" and str(exc).startswith("Classifier refused this article"):
                row.update(status="safely_withheld", decision="not_published", semantic_checked=False,
                           error=str(exc))
            else:
                row.update(status="unavailable", error=str(exc))
        rows.append(row)
        print("Recent-post check " + name + ": " + row["status"], flush=True)
    return rows


def ensure_ready(state, config, key, report, state_path):
    """Automatically hold posting on a failing self-check; retry on the next run."""
    today, identity = common.utc_now()[:10], bot.classifier_id(config)
    previous = state.get("classifier_health", {})
    if previous.get("date") == today and previous.get("classifier_id") == identity and previous.get("status") == "passed":
        report["classifier_health"] = {**previous, "cached": True}
        return
    rows = self_checks(config, key)
    passed = all(row["status"] == "passed" for row in rows)
    health = {"date": today, "classifier_id": identity, "status": "passed" if passed else "failed", "cases": rows}
    report["classifier_health"] = health
    state["classifier_health"] = health
    common.save_state(state_path, state)
    if not passed:
        raise common.SetupError("Classifier self-check failed. No publication allowed; the next scheduled run retries automatically.")
