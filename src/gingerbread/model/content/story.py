"""The seven nights, in words.

⚠ **Draft text.**  Written from the arc the design freeze fixes — the
stepmother talks the father into leaving the children in the forest; seven
nights later they meet her in the deep forest, at the place they were left —
and from each night's existing tagline.  It is here so the game *has* a story
between its levels; the partners writing the script should replace the strings
and leave the table alone.

Kept apart from ``stages.py`` because the two are edited by different people for
different reasons.  A writer changing a paragraph should never be looking at a
spawn interval, and a designer retuning a night should never risk a paragraph.
"""

from __future__ import annotations

from typing import Final, NamedTuple


class Beat(NamedTuple):
    """One night's opening card."""

    #: Two or three lines, second person, present tense.
    body: str
    #: The line under the title.  Short.
    heading: str


BEATS: Final[dict[int, Beat]] = {

    1: Beat(
        heading="回來的那天",
        body="你們帶著女巫屋子裡的東西回到村子。\n"
             "沒有人問你們去了哪裡。他們只看著你們手上的糖。\n"
             "村子已經餓了一整個冬天。"),

    2: Beat(
        heading="他們靠得更近",
        body="磨坊今天沒有轉。\n"
             "有人在你們的門外站了一整個下午，什麼也沒說。\n"
             "葛蕾特問你，昨天晚上那個人為什麼要看著她。"),

    3: Beat(
        heading="不只是森林裡",
        body="你在林邊認出了三張臉——都是白天跟你借過火的人。\n"
             "他們的樣子還在，走路的方式已經不是了。\n"
             "你開始不確定自己揮的是什麼。"),

    4: Beat(
        heading="霧裡的那張臉",
        body="市集空了。攤子還在，人不在。\n"
             "霧裡有東西經過，那張臉像極了村民——\n"
             "然後你想起來，村民的臉本來就是這個樣子。"),

    5: Beat(
        heading="教堂燒起來了",
        body="有人先點的火。沒有人承認。\n"
             "火光照得很遠，遠到你第一次看清楚有多少人站在外面。\n"
             "葛蕾特說她認得那件外套。"),

    6: Beat(
        heading="分不清在逃還是在追",
        body="村子燒了一整夜。\n"
             "你已經數不出來今天揮了幾次燈，也數不出來揮向了誰。\n"
             "葛蕾特沒有再問問題了。"),

    7: Beat(
        heading="回到被丟掉的地方",
        body="這條路你走過一次——那次是被人帶進來的。\n"
             "森林深處還是老樣子，連石頭的位置都沒變。\n"
             "有人在那裡等你們。她一直都在那裡等。"),
}


#: Shown instead of a beat in the endless mode, which has no story to advance.
ENDLESS_BEAT: Final = Beat(
    heading="沒有天亮",
    body="這一夜不會結束。\n"
         "你能做的只有站在她前面，看能站多久。")
