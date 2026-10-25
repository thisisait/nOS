# Iris component vocabulary against OpenUI

What we took from [OpenUI](https://github.com/thesysdev/openui)'s
`packages/react-ui/src/genui-lib/` (read 2026-10-25): component **names**, the
one-sentence **descriptions** a model reads, and **prop shapes**, as design
input. Not taken: its runtime, its React code, OpenUI Lang, or its idea that a
model writes a UI tree. Here a model picks one kind of a closed list and fills
it with data ([ssot/doctrine/generative-ui.md](../../../ssot/doctrine/generative-ui.md)).

The list is `Component` in `files/anatomy/thalamus/contract/src/renderers.rs`
(spec: `files/anatomy/contracts/thalamus-shell.yml` §2). The model-facing
subset, and one sentence per kind saying when to use it, is `SHOW_KINDS` /
`SHOW_ABOUT` in `thalamus/src/serve.rs`; the gate is
`tests/tool_schemas.rs::every_show_kind_says_when_to_use_it`.

## Inventory

| OpenUI | Ours | Note |
|---|---|---|
| Callout, TextCallout | `callout` (v12) | tone ok/info/warn/bad (the face's tone words, not theirs) |
| Steps, StepsItem | `steps` (v12) | adds `status`; theirs is a static how-to |
| FollowUpBlock, FollowUpItem | `follow_up` (v12) | a click fills the composer; theirs sends at once |
| (none) | `sources` (v12) | provenance: rows the person was shown, checked by serve |
| Text, BoldText, TextContent, Label, InlineHeader, MarkDownRenderer, CodeBlock | `markdown` | plain text, drawn as text nodes; links as text |
| ListBlock, ListItem | `list` | |
| EntityList | `record` | |
| Table | `table`, `table_results` | |
| Charts (bar, line, area, pie, scatter, single stacked bar) | `chart` | |
| Charts (horizontal bar, radar, radial) | missing | roadmap `genui-chart-shapes` |
| MetricIndicator | `kpi` | the number is serve's, never the model's |
| RadioGroup, CheckBoxGroup, Chips, OptionCards | `choice` | a question; the answer goes back to the model as data |
| Form, FormControl, Input, TextArea, Select, DatePicker, SwitchGroup | `form` | serve builds it from the table's live schema; the model never does |
| Slider | missing | a `form` number field with min/max covers the need |
| Tag, TagBlock | `list` tone / Badge | not a kind of its own |
| OverviewCardBlock, SnippetCardBlock | `dashboard` of `kpi` | roadmap `genui-fact-cards` |
| CompositeCardBlock, ContextCardBlock | missing | roadmap `genui-fact-cards` |
| EditableTable | out of scope | a write is a `row_diff_approval` card, one diff the person approves |
| Button, Buttons, IconButton, Action | out of scope | an action is code (`VIEW_ACTIONS`, face limbs), never data |
| Image, ImageBlock, ImageGallery, ImageText, ImageTextLarge, VisualCardBlock | out of scope | each needs a URL from the model; roadmap `genui-held-images` |
| Icon, IconText | out of scope | chrome; an icon name would be a lookup the model drives |
| Card, CardHeader, Stack, Separator, Carousel, Tabs, Accordion, SectionBlock, SectionItem, Modal | out of scope | layout and chrome; the shell decides layout |
| (ThemeProvider, model switcher; not in genui-lib) | out of scope | chrome; ours is `ModelPicker` with `model_options` |
| (none) | `tree`, `timeline`, `graph`, `sequence`, `knowledge_tree`, `dendrogram` | ours only |
| (none: tool call / tool result) | `dendrogram` (`read_run`) + `activity` phase | not a model-filled kind: the record of a call is the ledger's, not the caller's |

## Notice

The `callout`, `steps` and `follow_up` names, their prop shapes and the gist of
their descriptions follow OpenUI's genui-lib:

> The MIT License (MIT)
>
> Copyright (c) 2011-2024 Thesys Inc.
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in
> all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
> THE SOFTWARE.
