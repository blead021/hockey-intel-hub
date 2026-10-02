from pipeline.sentiment.match import Matcher

VAN, NJD, BUF, PIT = 23, 1, 7, 5
PLAYERS = [
    (1, "Quinn", "Hughes", VAN), (2, "Jack", "Hughes", NJD), (3, "Luke", "Hughes", NJD),
    (4, "Rasmus", "Dahlin", BUF), (5, "Owen", "Power", BUF), (6, "Elias", "Pettersson", VAN),
    (7, "Sidney", "Crosby", PIT), (8, "Retired", "Player", None),
]
ALIASES = [(pid, f"{first} {last}", "name") for pid, first, last, _ in PLAYERS] + [
    (pid, f"{first[0]}. {last}", "name") for pid, first, last, _ in PLAYERS] + [(7, "Sid the Kid", "nickname")]
TEAMS = [(VAN, "VAN", "Vancouver Canucks"), (NJD, "NJD", "New Jersey Devils"), (BUF, "BUF", "Buffalo Sabres"),
         (PIT, "PIT", "Pittsburgh Penguins"), (3, "NYR", "New York Rangers"), (2, "NYI", "New York Islanders")]
M = Matcher(PLAYERS, ALIASES, TEAMS)


def ids(text, team=None, status="matched"):
    return sorted(c.player_id for c in M.match(text, team) if c.status == status)


def test_full_names_and_initials():
    assert ids("Quinn Hughes was great tonight") == [1]
    assert ids("Q. Hughes and J. Hughes face off") == [1, 2]


def test_nickname():
    assert ids("Sid the Kid scores again") == [7]


def test_unique_surname_alone():
    assert ids("Dahlin is a Norris candidate") == [4]
    assert ids("dahlin lowercase does not count") == []


def test_shared_surname_settled_by_feed_team():
    assert ids("Hughes was everywhere", team=VAN) == [1]


def test_shared_surname_settled_by_team_named_in_text():
    assert ids("Canucks win as Hughes dominates") == [1]


def test_shared_surname_between_teammates_needs_review():
    # Jack and Luke both play for New Jersey, so the team alone cannot tell them apart.
    assert ids("Hughes scores for the Devils") == []
    assert ids("Hughes scores for the Devils", status="needs_review") == [2, 3]


def test_teammate_in_text_gives_context():
    assert ids("Pettersson to Hughes, what a play") == [1, 6]


def test_common_word_surname_needs_context():
    assert ids("Their Power play is 0 for 10") == []
    assert ids("Power and Dahlin anchor the Sabres blue line") == [4, 5]


def test_retired_players_and_new_york_city_are_ignored():
    assert ids("Player of the game") == []
    assert M.team_words.get("new york") is None and M.team_words.get("rangers") == {3}


def test_first_name_and_team_name_surnames_need_context():
    players = PLAYERS + [(9, "Connor", "McDavid", 22), (10, "Kyle", "Connor", 52), (11, "Cam", "York", 4)]
    m = Matcher(players, ALIASES + [(9, "Connor McDavid", "name")], TEAMS)
    found = sorted(c.player_id for c in m.match("Connor McDavid had 3 points against New York", None) if c.status == "matched")
    assert found == [9]
