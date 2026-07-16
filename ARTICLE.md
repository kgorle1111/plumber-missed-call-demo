# I built an AI agent for plumbers. Then a plumber's office manager taught me a $279/month lesson.

*Kannishk Naidu, July 2026*

Three days ago I had what felt like a sharp idea. Then a plumbing company's
office manager killed it in one sentence, and she was right to. This is the
write-up: the build, the autopsy, and the rules I'm keeping. I'm posting it
because the failure is more useful in public than the demo would have been.

## The idea that looked sound

I'm doing an AI engineering internship, and the assignment I gave myself was
simple. Pick a local business vertical in Santa Cruz, find a real pain, build an
AI tool for it, and sell it on a free-pilot-then-one-time-fee model. I did what
looked like diligence. I researched around 50 local business categories, threw
out anything with regulatory surface (no HIPAA, no fair-housing exposure), and
ranked what was left by pain-per-dollar.

The winner looked obvious: missed-call text-back for plumbers. The logic was
clean. A plumber under a sink physically cannot answer his phone. Industry
figures put missed calls at 25 to 40% for service businesses. A missed call is a
$300 to $3,000 job dialing the next result on Google. So when his phone rings
out, the caller instantly gets a text ("sorry, on a job, what's going on?"), and
a small agent collects the issue, address, name, preferred time, and photos over
SMS, then hands the plumber one clean summary to call back on.

Every piece of that logic is true. What's wrong with it comes later.

## The build

I built it production-shaped, mirroring a voice agent I'd built before, because
"demo" shouldn't mean "toy." The parts I'd defend in a code review:

Deterministic gates before the LLM. A text containing "I smell gas" gets a
verbatim safety line ("leave the building, call 911 / PG&E") from a regex, in
0 ms, with 100% reliability. A life-safety reply should never depend on a model
behaving, parsing, or even being up. Prompt injection works the same way: caught
by pattern, refused, and the agent has no tools, so a hostile text can produce a
weird reply but never an action.

One structured LLM call per turn. A Haiku-class model returns
`{decision, captured_fields, reply_text}` in one shot, with no separate
classify-then-generate round trip. The hard boundaries live in code as well as
the prompt: it never quotes a price, never promises an arrival time, never gives
DIY gas or electrical advice, and never asks for the phone number SMS already
handed us.

Parse failures are recoverable, not silent. A malformed model reply re-asks the
customer instead of escalating. A false page to the owner's personal phone at
6am is how a tool gets uninstalled.

Value receipts. Every missed call logs an event, and a rollup turns the pilot
into one number: estimated revenue recovered. A win the owner can't see gets
cancelled.

Hermetic tests plus live behavioral evals. 56 offline tests cover the money and
safety paths with zero keys, and a 12-case live eval grades the model on the
contract: never prices, one question per text, escalates anger, refuses DIY gas
advice.

Running cost, all in, on the client's own accounts: about $10 a month. I had a
pitch plan, a cold-call script, and five researched local plumbers to call.

## The autopsy, in two conversations

Instead of pitching, I booked a discovery sit-down. No product mention, just
"I'm an intern building for trades, tell me how the work actually runs." Best
decision of the project.

The first plumber listened to my questions about missed calls and told me he
already has this. It's called Housecall Pro. It does his scheduling, invoicing,
payments, and yes, the phone stuff.

Then I called another local plumbing company and spoke to their office manager.
They pay $279 a month for their platform. Does the missed-call handling work?
"It works. It does all of this." I asked what the software still doesn't fix.
Her answer was nothing. It's perfect. Vertical closed.

Then I ran the competitive scan I should have run before I wrote a single line
of code. It took about ten minutes.

Podium (founded 2014, roughly $218M raised) has sold missed-call text-back and
review management to local businesses for about a decade. GoHighLevel has had
missed-call text-back on by default since August 2021: $97 a month, ten-minute
setup, thousands of reseller agencies with pre-built "plumber snapshots." The
field-service platforms (Housecall Pro, Jobber, ServiceTitan) all bundle it, and
all now sell AI receptionist add-ons on top. The AI-voice wave (Avoca, Rosie,
Allo, RingCentral AIR, and others) has been targeting trades specifically since
2023 and 2024. ElevenLabs has a plumbing landing page.

My "sharp idea" was a ten-year-old product, commoditized five years ago, now a
checkbox inside software my prospects already pay for. And here's the part that
actually stings: every fact above was one search away the whole time. I
researched the customer thoroughly, down to the town, the businesses, and the
owners' names, and never once searched for the competition.

## I checked my other two verticals. Same story, worse.

My backups were barbershops (automated review requests plus an "it's been four
weeks, want your usual slot?" rebooking text) and auto repair shops (status
texts, reminders, review requests). The scan:

Barbershops. Square Appointments, free tier for solo barbers and $49 a month for
Plus, automatically collects Google reviews after an appointment and ships a
feature literally named "Lapsed Booker automation." Both of my features, by
name, in the incumbent, starting at free. Booksy covers the rest at $30 a month.

Auto repair. Shopmonkey ($199+) and Tekmetric ($179+) bundle status texts and
review requests. There's one genuine crack: neither handles declined-service
follow-up well (the "you deferred that brake job, still want it?" sequence at
day 14 and 30). But the blog documenting that gap belongs to an automation
agency already selling into it.

Three for three. The pattern wasn't "plumbing is crowded." It was that I kept
generating product ideas from imagined pain instead of discovered gaps, and
imagined pains are exactly the ones platforms productized years ago, because
they were imaginable to funded teams too.

## What I actually learned

**1. The bundle beats the point solution.** An SMB paying $279 a month doesn't
want a better $500 point tool. They want fewer vendors and one login. My tool
wasn't competing against voicemail. It was competing against a checkbox in
software they already trust, and down-market, being part of the bundle usually
wins.

**2. A build recommendation without a dated competitor scan is incomplete.**
This is a literal rule in my playbook now. Before "build X for market Y," search
the incumbents, their launch dates, their prices, and whether X is already a
feature of a platform the buyer pays for. Present that scan with the
recommendation. Ten minutes of search versus three days of build: I paid full
price for this one.

**3. Willingness to pay was never the problem.** $279 a month, $3,350 a year,
from a local plumbing company, no hesitation. The market pays real money for
software. It just doesn't pay outsiders for features it already owns.

**4. Office managers beat owners for discovery.** The owner knows what hurts. The
office manager, who drives the software eight hours a day, knows what the $279
doesn't fix: the spreadsheet she still keeps on the side, the data she re-types
between systems, the report she rebuilds every Friday. That leftover work is the
only ground where a solo builder beats a funded platform, because it's too
specific for a platform to bother with.

**5. The discovery question that matters isn't "what hurts?"** It's "what hurts
that your current software doesn't fix, and what do you pay for that software?"
The first question finds pains. The second finds the ones without a listicle,
without a GoHighLevel snapshot, without a checkbox.

## What survived

The code, unchanged: deterministic safety gates, a structured single-call agent,
value receipts, hermetic tests. That architecture is product-agnostic, and it
retargets to whatever discovery finds next by swapping a prompt and a value
table. The relationships survived too. Two plumbers and an office manager now
know a local builder who asks decent questions. And the process changed:
discovery first, competitor scan with every recommendation, build last.

Back to the drawing board, but this time the drawing board has data on it.

---

*The demo repo (agent, gates, evals, receipts) is public. If you run a local
service business and there's a spreadsheet your software should have killed by
now, I want to hear about it.*
