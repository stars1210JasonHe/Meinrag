# MEINRAG Frontend Layout (Current)

## 1. Full Page Layout

```
+===========================================================================+
|                              HEADER                                       |
|  MEINRAG            3 documents  [ai-ml]  [+ New Chat]  [@ Admin v]      |
+===========================================================================+
|          |                                                                |
| SIDEBAR  |                    CHAT AREA                                   |
| (320px)  |                   (flex: 1)                                    |
|          |                                                                |
|          |                                                                |
|          |                                                                |
|          |                                                                |
|          |                                                                |
|          |                                                                |
|          |                                                                |
|          |                                                                |
|          |  +----------------------------------------------------------+  |
|          |  | Ask a question...                                   [>] |  |
|          |  +----------------------------------------------------------+  |
+----------+----------------------------------------------------------------+
```

## 2. Header Detail

```
+===========================================================================+
|                                                                           |
|  MEINRAG        3 documents  [ai-ml]   [+ New Chat]   [@ Admin  v]       |
|                                                                           |
|  (h1 logo)     (doc count)  (active    (new session    (user selector     |
|                              badge)     button)         dropdown)         |
|                                                                           |
+===========================================================================+
                                                          |
                                    User Menu (on click)  v
                                    +---------------------+
                                    | @ Admin        (*)  |
                                    | @ Bob               |
                                    | @ Charlie           |
                                    |---------------------|
                                    | + New User          |
                                    +---------------------+
                                              |
                                    New User Form (expanded)
                                    +---------------------+
                                    | [user-id         ]  |
                                    | [Display Name    ]  |
                                    | [Create] [Cancel]   |
                                    +---------------------+
```

## 3. Sidebar Detail

```
+---------------------------+
| SIDEBAR (320px)           |
|                           |
| # Collections             |
| +- - - - - - - - - - - -+|
| | [* All Documents (5) ] ||  <-- active = purple bg
| | [  ai-ml (2)         ] ||
| | [  legal (1)         ] ||
| | [  finance (2)       ] ||
| +- - - - - - - - - - - -+|
|                           |
| # Documents               |
| +- - - - - - - - - - - -+|
| | report.pdf        [..] ||  <-- [..] = action icons
| | |ai-ml| |finance|      ||  <-- collection tags
| | 12 chunks              ||
| |----------------------- ||
| | contract.docx      [..]||
| | |legal|                 ||
| | 8 chunks               ||
| +- - - - - - - - - - - -+|
|  (scrollable, max 300px)  |
|                           |
| # Upload                  |
| +- - - - - - - - - - - -+|
| | [  Upload Document   ] ||  <-- primary button (purple)
| | [* Auto-Categorize   ] ||  <-- secondary button (outline)
| | Uploading to: ai-ml    ||  <-- hint when collection selected
| +- - - - - - - - - - - -+|
+---------------------------+
```

### Document Item Actions

```
+-----------------------------------------------+
| report.pdf                   [E] [R] [D] [X]  |
| |ai-ml| |finance|                              |
| 12 chunks                                      |
+-----------------------------------------------+
  [E] = Edit collections (pencil icon)
  [R] = AI Reclassify (refresh icon)
  [D] = Download (download icon)
  [X] = Delete (trash icon, red on hover)
```

### Document Edit Mode (inline)

```
+-----------------------------------------------+
| report.pdf                   [E] [R] [D] [X]  |
| +-------------------------------------------+ |
| | ai-ml, finance, research                  | |  <-- editable text input
| +-------------------------------------------+ |
| [Save] [Cancel]                                |
| 12 chunks                                      |
+-----------------------------------------------+
```

## 4. Chat Area - Welcome Screen (no conversation yet)

```
+----------------------------------------------------------------+
|                                                                |
|                                                                |
|   Welcome to MEINRAG                                           |
|   Your intelligent document assistant                          |
|   ─────────────────────────────────────                        |
|                                                                |
|   Ask questions about your documents in natural language.      |
|   Works with English and Chinese.                              |
|                                                                |
|   +-- Get Started --------+  +-- Features ----------------+   |
|   | 1. Upload documents   |  | * Multi-Collection:        |   |
|   | 2. Organize into      |  |   Documents can belong to  |   |
|   |    collections        |  |   multiple categories      |   |
|   | 3. Ask any question   |  | * User Profiles:           |   |
|   |                       |  |   Isolated document spaces |   |
|   |                       |  | * AI Classification:       |   |
|   |                       |  |   Auto-categorize docs     |   |
|   |                       |  | * Source Citations:        |   |
|   |                       |  |   Expand chunks, download  |   |
|   +-----------------------+  +----------------------------+   |
|                                                                |
|                (vertically centered in chat area)              |
|                                                                |
+----------------------------------------------------------------+
| [Ask a question...                                        ] [>]|
+----------------------------------------------------------------+
```

## 5. Chat Area - Conversation with Document Sources

```
+----------------------------------------------------------------+
|                                                                |
|                          What does the report say about   [U]  |
|                          quarterly revenue growth?             |
|                                                                |
|  [A] The report indicates that quarterly revenue grew by       |
|      15.3% year-over-year, driven primarily by the expansion   |
|      of the cloud services division...                         |
|                                                                |
|      SOURCES                                                   |
|      +------------------------------------------------------+ |
|      | > report.pdf              p.12  chunk 3  [download]   | |
|      +------------------------------------------------------+ |
|      | v annual-summary.pdf      p.5   chunk 1  [download]   | |
|      | +--------------------------------------------------+  | |
|      | | "Revenue for Q3 2025 reached $4.2B, representing |  | |
|      | |  a 15.3% increase compared to Q3 2024..."        |  | |
|      | +--------------------------------------------------+  | |
|      +------------------------------------------------------+ |
|                                                                |
|  [U] = user message (right-aligned, purple bg)                 |
|  [A] = assistant message (left-aligned, grey bg)               |
|  >   = collapsed source (click to expand)                      |
|  v   = expanded source (showing chunk content)                 |
|                                                                |
+----------------------------------------------------------------+
| [Ask about ai-ml documents...                             ] [>]|
+----------------------------------------------------------------+
```

## 6. Chat Area - Web Search Fallback Response

```
+----------------------------------------------------------------+
|                                                                |
|                          What is the latest news about   [U]   |
|                          quantum computing?                    |
|                                                                |
|  [A] [Web Search] badge (green)                                |
|      Based on web search results, recent developments in       |
|      quantum computing include Google's new 1000-qubit chip... |
|                                                                |
|      WEB SOURCES                                               |
|      +------------------------------------------------------+ |
|      | (globe) Google Announces Quantum Breakthrough          | |  <-- green border
|      +------------------------------------------------------+ |
|      | (globe) MIT Quantum Computing Review 2025             | |
|      +------------------------------------------------------+ |
|      | (globe) Nature: Advances in Error Correction          | |
|      +------------------------------------------------------+ |
|                                                                |
|      (globe) = green globe icon instead of chevron             |
|      No download button (web sources)                          |
|      No page/chunk info (web sources)                          |
|                                                                |
+----------------------------------------------------------------+
| [Ask a question...                                        ] [>]|
+----------------------------------------------------------------+
```

## 7. Loading State (Thinking)

```
+----------------------------------------------------------------+
|                                                                |
|                          What is the summary?             [U]  |
|                                                                |
|                         (spin) Thinking...                     |
|                                                                |
|                   (centered, fills remaining space)             |
|                                                                |
+----------------------------------------------------------------+
| [Ask a question...  (disabled)                            ] [>]|
+----------------------------------------------------------------+
```

## 8. System Messages (uploads, errors, etc.)

```
+----------------------------------------------------------------+
|                                                                |
| +------------------------------------------------------------+|
| | Uploaded: report.pdf (AI suggested: ai-ml, research)       ||  <-- yellow bg
| | Collections: ai-ml, research                                ||
| +------------------------------------------------------------+|
|                                                                |
| +------------------------------------------------------------+|
| | Error: The AI provider returned an error. Try again.       ||  <-- yellow bg
| +------------------------------------------------------------+|
|                                                                |
+----------------------------------------------------------------+
```

## 9. Connection Error Banner

```
+===========================================================================+
|  MEINRAG            0 documents              [+ New Chat]  [@ Admin v]    |
+===========================================================================+
| !! Cannot connect to backend at http://localhost:8000.  [Retry]  !!       |
+===========================================================================+
|          |                                                                |
| SIDEBAR  |                    CHAT AREA                                   |
```

## Component Tree Summary

```
App
 +-- Header
 |    +-- Logo ("MEINRAG")
 |    +-- Header Info
 |         +-- Document Count ("3 documents")
 |         +-- Active Collection Badge ("[ai-ml]")
 |         +-- New Chat Button
 |         +-- User Selector
 |              +-- User Menu Dropdown
 |                   +-- User List
 |                   +-- New User Form
 |
 +-- Connection Error Banner (conditional)
 |
 +-- Main Container (flex row)
      +-- Sidebar (320px)
      |    +-- Collections Section
      |    |    +-- "All Documents" button
      |    |    +-- Collection buttons (with counts)
      |    +-- Documents Section
      |    |    +-- Document Items (scrollable)
      |    |         +-- Filename
      |    |         +-- Collection Tags (clickable)
      |    |         +-- Chunk Count
      |    |         +-- Action Icons (edit, reclassify, download, delete)
      |    |         +-- Inline Edit Form (conditional)
      |    +-- Upload Section (pinned to bottom)
      |         +-- "Upload Document" button
      |         +-- "Auto-Categorize" button
      |         +-- Upload Hint text
      |
      +-- Chat Container (flex: 1)
           +-- Messages Area (scrollable)
           |    +-- Welcome Screen (when no conversation)
           |    +-- Message Bubbles
           |    |    +-- User Messages (right-aligned, purple)
           |    |    +-- Assistant Messages (left-aligned, grey)
           |    |    |    +-- Web Search Badge (conditional, green)
           |    |    |    +-- Answer Text
           |    |    |    +-- Sources Panel
           |    |    |         +-- Document Sources (chevron, expand, download)
           |    |    |         +-- Web Sources (globe icon, green border)
           |    |    +-- System Messages (full-width, yellow)
           |    +-- Thinking Indicator (conditional)
           |
           +-- Input Bar
                +-- Text Input (with placeholder)
                +-- Send Button (purple circle)
```
