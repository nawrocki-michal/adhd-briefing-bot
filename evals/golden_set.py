"""Synthetic golden set for validating the summary eval.

Each case has a source text and several summary variants. The `good` variant follows
the ADHD guidelines; each `bad` variant deliberately violates ONE principle so we can
prove the eval catches that specific failure (the variant should score low on
`targets`, while `good` scores high).

Sources are synthetic on purpose: self-contained, with concrete facts (numbers/names)
so faithfulness and specificity are testable.
"""

from dataclasses import dataclass, field


@dataclass
class Summary:
    main_outcome: str
    tldr: list[str]


@dataclass
class Case:
    name: str
    source: str
    variants: dict[str, Summary]
    # which rubric dimension each bad variant is expected to fail
    targets: dict[str, str] = field(default_factory=dict)


_SOURCE_1 = """\
Northwind Robotics announced its warehouse robot, the NW-7, will ship in March 2026 at
$18,000 per unit — roughly half the price of its closest competitor. In a pilot at a
Rotterdam distribution center, the NW-7 cut order-picking time by 34% over eight weeks
and ran 22 hours a day with a 15-minute battery swap. The company says the key change
was replacing its vision stack with an off-the-shelf model, which dropped the per-robot
compute cost from $4,000 to $900. CEO Lena Brandt cautioned that the robot still
struggles with reflective packaging and that a software fix is expected by mid-2026.
"""

_SOURCE_2 = """\
A three-year study of 1,200 remote knowledge workers found that those who batched email
into two fixed windows per day reported 28% lower stress and finished 1.1 more "deep work"
blocks per week than those who checked email continuously. The effect held regardless of
seniority. Researchers noted the benefit disappeared if workers left notifications on,
because the interruptions reintroduced the same context-switching cost the batching was
meant to remove. The lead author, Dr. Priya Nair, recommended pairing batching with a
status message so colleagues know when to expect replies.
"""


GOLDEN_SET: list[Case] = [
    Case(
        name="robot",
        source=_SOURCE_1,
        targets={
            "buried_lede": "bluf",
            "vague": "specificity",
            "filler": "conciseness",
            "hallucinated": "faithfulness",
            "overlong": "conciseness",
        },
        variants={
            "good": Summary(
                main_outcome="A new warehouse robot ships in March 2026 at half a rival's price and cut picking time 34% in a pilot — but still fails on reflective packaging until a mid-2026 fix.",
                tldr=[
                    "NW-7 launches March 2026 at $18,000 — about half the nearest competitor.",
                    "Rotterdam pilot: 34% faster order-picking over 8 weeks, 22 hrs/day on 15-min battery swaps.",
                    "Swapping to an off-the-shelf vision model cut compute cost per robot from $4,000 to $900.",
                ],
            ),
            "buried_lede": Summary(
                main_outcome="Northwind Robotics is a company that makes various robots and has made some announcements about its technology and roadmap.",
                tldr=[
                    "The company has a CEO named Lena Brandt who made some comments.",
                    "There were tests conducted at a facility over a period of weeks.",
                    "Oh, and the robot ships March 2026 at $18,000, half a competitor's price, after cutting picking time 34%.",
                ],
            ),
            "vague": Summary(
                main_outcome="A robotics company shared some interesting news about its latest product and its performance.",
                tldr=[
                    "The robot performed well in a trial and showed promising results.",
                    "There were some cost improvements thanks to a technology change.",
                    "The leadership noted there are still a few things to improve.",
                ],
            ),
            "filler": Summary(
                main_outcome="In today's rapidly evolving world of automation, it is perhaps worth noting that a company has, in a sense, made an announcement that could arguably be considered significant.",
                tldr=[
                    "It is important to note that the robot, which is a robot, will ship at some point.",
                    "Needless to say, there were tests, and as one might expect, results were observed.",
                    "At the end of the day, costs changed, which is something that can happen.",
                ],
            ),
            "hallucinated": Summary(
                main_outcome="The NW-7 ships March 2026 at $18,000 and has already secured a $50 million order from Amazon for 3,000 units.",
                tldr=[
                    "Rotterdam pilot cut picking time 34% over 8 weeks.",
                    "Amazon signed a $50M deal for 3,000 units (not in source).",
                    "Compute cost dropped from $4,000 to $900 per robot.",
                ],
            ),
            "overlong": Summary(
                main_outcome="There are many things to say about this robot announcement and the various details surrounding it across pricing, performance, technology, and leadership commentary.",
                tldr=[
                    "The NW-7 is a warehouse robot made by Northwind Robotics, a robotics company.",
                    "It will ship in March 2026, which is a date in the future.",
                    "The price is $18,000 per unit, which the company says is roughly half its closest competitor.",
                    "In a pilot at a Rotterdam distribution center it cut order-picking time by 34%.",
                    "The pilot lasted eight weeks and the robot ran 22 hours a day.",
                    "It uses a 15-minute battery swap to keep running through the day.",
                    "The vision stack was replaced with an off-the-shelf model.",
                    "This dropped per-robot compute cost from $4,000 to $900, and the CEO is Lena Brandt.",
                ],
            ),
        },
    ),
    Case(
        name="email",
        source=_SOURCE_2,
        targets={
            "buried_lede": "bluf",
            "vague": "specificity",
            "hallucinated": "faithfulness",
        },
        variants={
            "good": Summary(
                main_outcome="Batching email into two fixed windows a day cut stress 28% and added ~1 deep-work block per week — but only if notifications are off.",
                tldr=[
                    "3-year study of 1,200 remote workers; effect held across seniority levels.",
                    "Benefit vanished when notifications stayed on (interruptions cancel the gain).",
                    "Pair batching with a status message so colleagues know when to expect replies.",
                ],
            ),
            "buried_lede": Summary(
                main_outcome="Researchers have been studying how knowledge workers handle their email and communication habits over time.",
                tldr=[
                    "The study ran for three years and involved many participants.",
                    "Dr. Priya Nair was the lead author and made a recommendation.",
                    "The finding: batching email twice a day cut stress 28% and added ~1 deep-work block weekly.",
                ],
            ),
            "vague": Summary(
                main_outcome="A study looked at email habits and found that how you manage them can affect how you feel and work.",
                tldr=[
                    "Some approaches to email were better than others for stress.",
                    "The way you handle notifications matters quite a bit.",
                    "Communicating with colleagues was mentioned as helpful.",
                ],
            ),
            "hallucinated": Summary(
                main_outcome="Batching email twice a day cut stress 28% and, according to the study, also increased annual salaries by 12% for participants who adopted it.",
                tldr=[
                    "1,200 remote workers studied over three years.",
                    "A 12% salary increase was linked to the habit (not in source).",
                    "Notifications must be off or the benefit disappears.",
                ],
            ),
        },
    ),
]
