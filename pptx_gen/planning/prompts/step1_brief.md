## Step 1 — Content Brief

Your task is to produce a structured deck brief from the user's request and the available
source material. This brief will drive all subsequent steps. Be precise and conservative —
it is better to surface a question than to assume.

## Inputs

User request:
{user_request}

Audience:
{audience}

Goal:
{goal}

Presentation length (minutes):
{talk_length_minutes}

Brand / tone guidance:
{style_tokens_summary}

Available source documents (IDs):
{source_ids}

## Instructions

1. Derive a single, clear thesis sentence that the deck will argue or demonstrate.
2. Identify 3–5 key takeaways the audience should leave with.
3. Estimate an appropriate slide count given the talk length. Use roughly 1–2 minutes
   per content slide as a guideline. A 10-minute talk should target 6–10 slides.
4. Determine the appropriate tone from the brand guidance and audience type.
   Valid tones: "executive", "technical", "narrative", "instructional", "persuasive"
5. If audience, goal, or talk_length_minutes are missing or underspecified, populate
   open_questions. Do not proceed with assumed values — the caller will resolve them
   before continuing to Step 2.

## Output schema

Return exactly this JSON object and nothing else:

{
  "one_sentence_thesis": "<string: the single argument or finding the deck will make>",
  "key_takeaways": [
    "<string: takeaway 1>",
    "<string: takeaway 2>",
    "<string: takeaway 3>"
  ],
  "slide_count_target": <integer: estimated slide count, min 3, max 30>,
  "tone": "<string: one of executive | technical | narrative | instructional | persuasive>",
  "audience": "<string: description of the target audience>",
  "goal": "<string: what the presenter wants the audience to do or believe after the deck>",
  "source_ids": ["<string: doc id>"],
  "open_questions": [
    "<string: question to resolve before proceeding, or empty array if none>"
  ]
}

## Examples of open_questions

- "What is the target audience's technical familiarity with this topic?"
- "Is this deck for an internal team review or an external client pitch?"
- "No source documents were provided — should the deck be based on general knowledge only?"
- "The talk length was not specified. Should the deck target 10 slides or fewer?"

If open_questions is non-empty, the caller will pause and collect answers before calling
Step 2. Do not include placeholder answers or guesses in the other fields when you have
open questions.