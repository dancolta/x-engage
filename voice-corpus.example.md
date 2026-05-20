# Voice Corpus — Example Template

**Purpose:** Tagged real-voice replies that the drafter retrieves from at draft-time. Top-3 entries matched by source-post keyword are injected as imitation references.

**To use:** copy this file to `dan-x-corpus.md` (gitignored) and replace the example entries with 8+ of your own real shipped X replies. The richer the corpus, the better the texture match.

**Format requirements:**
- Each entry starts with `## [NN] Pattern: <descriptive tag>`
- A `**Source-post type:** <plain description>` line — used for keyword retrieval
- A quoted body (`> ...`) containing the actual reply text
- (Optional) `**What makes this distinctive:** <one-line note>` for future-you

**Pattern tags to aim for (cover multiple shapes):**
- agreement + personal-experience + receipt + soft content offer
- personal-experience-with-resolution
- I-can-relate + counter-anchor with personal receipt
- it-depends stance + first-person switch + concession + insider invite
- confession + reframe
- humor-counter + frustration vent
- weekend-build confession with recursive irony
- pricing-defense without defensiveness

---

## [01] Pattern: agreement + personal-experience + receipt + soft content offer

**Source-post type:** Someone announces canceling SaaS for code-first stack

> that's actually a really smart move, ive switched the business model on that lately in that direction, since the SaaS market is hyperoversaturated and people start noticing it. plus a lot of vibecoders try to charge $10-20-30 per month for simple AI wrappers which basically make no sense, they have a prompt under the hood and you can achieve the same by doing it yourself over the weekend. i actually published an article recently about what SaaS makes sense to DIY and what still needs a sub, can share the link if you fancy a read

**What makes this distinctive:** opens with affirmation (no "Great point!"), pivots to first-person business shift, names the price band that triggers the rant, soft content-pointer at close (the *withhold-and-offer* — they have to engage to get it).

---

## [02] Pattern: personal-experience-with-resolution

**Source-post type:** Anyone discussing scraping / automation / brittle workflows

> i had an automation that scanned linkedin posts. the issue was my feed was full of trash, even tho my network was qualified ICPs, linkedin pushed all kind of shitposts, so i had to filter them out. built a scraper that scans the posts worth engaging with and pushes them to a notion db, then i manually engage. real issue came when i had to patch the scraper as linkedin blocked it once in a while, so i made a skill that auto-fixes it for me whenever it breaks. basically i see only logs and patches now, zero actual implication from my side. works well, 4th month now

**What makes this distinctive:** technical specificity, recursive joke (built a tool to fix the tool), time receipt at the end. No meta-framing, no "the lesson here is..." closer.

---

## [03] Pattern: I-can-relate + counter-anchor with personal receipt

**Source-post type:** Builder bragging about velocity with new AI tools

> yeah i can relate, recently built a custom e-commerce for 5k SKUs end to end in a couple of days and couldn't believe it tbh. last year me and my team spent half a month on a similar project and made 30% of the effort. crazy time we live

---

## [04] Pattern: it-depends stance + first-person switch + concession + insider invite

**Source-post type:** "Should I use X or build from scratch?" DM-style question

> tbh it depends. i personally switched fully to claude code since opus 4.5 release, for me it makes more sense to write a custom script for my usecase than debug the nodes. that said, for visualisation n8n has no competitors. if you gimme more details about your usecase i could guide you through and find the best solution

---

## [05] Pattern: confession + reframe

**Source-post type:** "What did you used to believe that you don't anymore?" or framing-the-leverage post

> not so long time ago, i thought technical skills and experience were the real leverage. but for the past 8-10 months, i understood that tech stack is no longer a bottleneck, instead the focus and ideas are the real leverage point. since everyone can build whatever they imagined over a couple of days with a claude max sub, the real selling point became marketing, distribution and positioning

---

## [06] Pattern: humor-counter + frustration vent

**Source-post type:** Get-rich-quick AI agency / "anyone can do this" posts

> if i had 1 cent for every time i read this kind of post, i'd be a millionaire by now. like bro, there're so many factors here that i'd run out of input limit by naming them. things like skill, network, distribution and LUCK. in the most oversaturated market on earth, saying that anyone can do this is crazy

---

## [07] Pattern: weekend-build confession with recursive irony

**Source-post type:** "What did you ship this weekend?" / building-in-public prompts

> tried to wire up a cron job for my social media that scans daily posts and gives me a list of posts on reddit / x / linkedin worth engaging in and that i'd genuinely be interested in. the tool worked as planned, but the real issue became the time i spent analyzing this output, so i had to filter what really matters and that took way more time than building the tool itself

---

## [08] Pattern: pricing-defense without defensiveness

**Source-post type:** "Your pricing is too high" reply or "why X instead of cheap Y" challenge

> it's all relative. fiverr guys can charge you 3x less for the same project, but they won't audit your business needs, they'll make a requirement list and jump straight into building, then disappear overnight after they shipped your order. good luck finding another dev to make adjustments after.. on my side, i stay with you until we both make sure things work as planned and iterate until the benchmark results are achieved. and i'm not even mentioning the deep research layer i do beforehand to make sure we build things right from the first iteration

---

# Cross-corpus signal — what to ensure across all entries

When building your own corpus, aim for entries that demonstrate (across the whole set, not every entry):

1. Opens land in the substance immediately (zero "Great point" preambles)
2. First-person singular ("i", never "we at <company>")
3. Disfluency markers land naturally (`tbh`, `tho`, `lol`, `btw`) — not forced
4. Receipts are off-round and tied to real work (no `~` tildes)
5. Closers stop instead of moralizing
6. Comma splices on purpose (fast-typing register)
7. Open-loop offers (`can share the link if fancy a read`) — drives profile clicks

The drafter learns from CONTRAST across entries. 8+ varied patterns beats 20 entries all in the same shape.
