<!--
Drafting notes (removed before the page is served). Register LEG-H6. No designation is filed with the US
Copyright Office yet, so the page neither says nor implies one, and claims no safe harbour (docs/legal/open-items.md). The contact's name comes from part7/legal_pages.py and the address from the server setting SIMON7_POSTAL_ADDRESS. The operator evict command is `python -m part7 evict remove <entry>
--reason <notice>` (part7/evict_cli.py; `reinstate` after a counter notice; every action is kept in
`<state>/evictions.jsonl`). A person who uploaded signed out leaves no contact, so the page promises no notice to the
uploader (a11y-copy B8).
Operator acceptance, 3 November 2026: no lawyer reviewed this page. The operator accepted it without one, and the review line
was removed as the record of that acceptance. Names come from part7/legal_pages.py TOKENS; the address token from legal_pages.postal_address().
Notice, counter notice, court and restore wording: 17 USC 512(c)(3)(A), (g)(2) and (g)(3)(D), read at
https://www.law.cornell.edu/uscode/text/17/512. Telling the uploader is section 512(g)(2)(A); no code sends this mail, so
it is an operator step with each evict.
The prod start check (lane compute, part7/legal_drafts.py) refuses this page while it holds an operator placeholder or
the review banner. Keep every placeholder on one line in its upper case form so the check finds it.
-->
# Copyright and takedown

Last updated 3 November 2026.

## Report content

{{COMPANY_NAME}} provides this service. If a movement or video on Simon infringes your copyright, send a notice to the person who
handles copyright notices for {{COMPANY_NAME}}:

- {{DMCA_AGENT_NAME}}
- {{DMCA_AGENT_ADDRESS}}
- [support@simon.live](mailto:support@simon.live)

The notice must include:

- the physical or electronic signature of the copyright owner, or of a person authorised to act for them;
- the work you say is infringed;
- the address of the content on Simon (the link of the movement or the take);
- your address, telephone number and, if you have one, email address;
- a statement that you believe in good faith the use is not authorised by the owner, its agent or the law;
- a statement that the notice is accurate and, under penalty of perjury, that you may act for the owner.

## What happens next

We remove the content from public view and keep a record of each removal. If the uploader has an account, we write to
its email address to say what was removed and that they may send a counter notice. A person who uploaded with no
account left no contact, so we cannot reach them.

## Counter notice

The person who uploaded it may send a counter notice to the same contact with:

- their physical or electronic signature;
- the content that was removed and where it was;
- a statement under penalty of perjury that they believe in good faith it was removed by mistake or misidentification;
- their name, address and telephone number;
- their consent to the jurisdiction of the federal district court for the district where that address is or, if it is
  outside the United States, of any district where we may be found;
- their agreement to accept service of process from the person who sent the notice, or that person's agent.

We send a copy to the person who sent the notice and tell them we will restore the content in 10 business days. We
restore it 10 to 14 business days after the counter notice unless they tell that contact they have filed a court action.

## Repeat infringers

We close the accounts of people who infringe repeatedly.
