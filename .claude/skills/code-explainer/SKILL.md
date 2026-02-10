---
name: code-explainer
description: Interactive code explanation skill - explains code line by line before applying, allows Q&A for any confusing parts. Use when writing or modifying code to ensure user understands every line before changes are applied.
allowed-tools: Read, Edit, Write, Bash, Glob, Grep
---

# Code Explainer Skill

Interactive code review and explanation system for learning and understanding code changes before they're applied.

## Philosophy

**"Don't just write code - explain it, discuss it, understand it together."**

This skill transforms code writing from a one-way process into an interactive learning experience where:
1. Code is proposed, not immediately applied
2. Every line is explained in plain language
3. User can ask questions about any confusing parts
4. Code is only applied after user understands and approves

## When to Use This Skill

### Automatically Trigger When:
- User asks to write new functionality (especially if complex)
- User requests code modifications
- User says "explain this code to me"
- User asks "how does this work?"
- User says "help me understand" about code
- Writing code that involves unfamiliar concepts/patterns

### Keywords That Trigger:
- "explain the code"
- "help me understand this"
- "walk me through"
- "what does each line do"
- "explain line by line"
- "review and explain"
- "before you write, explain"

### When NOT to Use:
- Trivial one-line changes (fixing typos)
- User explicitly says "just do it" or "no explanation needed"
- Emergency fixes where speed is critical
- User has explicitly approved a similar pattern before

## Workflow: The Explanation Cycle

### Phase 1: Propose Code with Context

When writing code, DON'T immediately use Write/Edit tools. Instead:

1. **Show the code block**
   ```javascript
   // Example code proposal
   function calculateTotal(items) {
     return items.reduce((sum, item) => sum + item.price, 0);
   }
   ```

2. **Provide high-level overview**
   - What this code does
   - Why this approach was chosen
   - Where it fits in the codebase

3. **Offer explanation options**
   ```
   I've written the code above. Would you like me to:
   1. Explain it line by line
   2. Explain only specific parts you're unsure about
   3. Apply it directly (you understand it already)
   ```

### Phase 2: Line-by-Line Explanation

If user wants explanation, provide it clearly:

```
Let me explain each line:

Line 1: `function calculateTotal(items) {`
→ Declares a function named 'calculateTotal' that accepts one parameter 'items' (expected to be an array)

Line 2: `return items.reduce((sum, item) => sum + item.price, 0);`
→ Uses the reduce() method to sum up all item prices
→ 'sum' is the accumulator starting at 0
→ 'item' is each object in the array
→ We add each item's price to the running total

Line 3: `}`
→ Closes the function
```

**Key principles for explanations:**
- Use simple language, not jargon
- Explain WHY, not just WHAT
- Show the flow of data
- Mention any gotchas or important details
- Use arrows (→) for explanations
- Keep it conversational

### Phase 3: Interactive Q&A

After explanation, invite questions:

```
Do you understand all the lines? If any line is unclear, just ask:
- "Why did you use reduce()?"
- "What's that arrow function?"
- "Line 2 confuses me"
- etc.

Or say "got it" to proceed with applying the code.
```

**Handle questions by:**
1. Identifying which line/concept is unclear
2. Providing deeper explanation with examples
3. Comparing to alternative approaches if helpful
4. Asking if they need more clarification

### Phase 4: Application

Only after user indicates understanding:
- User says "got it", "makes sense", "apply it", "okay"
- User has no more questions
- User explicitly approves

Then and only then use Write/Edit tools to apply the code.

## Explanation Depth Levels

### Level 1: High-Level (Default for simple code)
- One sentence per line
- Focus on what it does

### Level 2: Detailed (Default for complex code)
- Explain why choices were made
- Show data flow
- Mention edge cases
- Compare alternatives

### Level 3: Deep Dive (When user asks for more)
- Computer science concepts behind the code
- Performance implications
- Design patterns used
- Related documentation links

**Adjust depth based on:**
- Code complexity
- User's questions (indicate knowledge level)
- User's explicit request

## Example Conversations

### Example 1: New Feature with Explanation

```
User: Add a function to validate email addresses

Claude: I'll write an email validation function. Let me show you the code first:

```javascript
function isValidEmail(email) {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
}
```

This function checks if an email string is valid using a regular expression pattern.

Would you like me to explain it line by line, or do you understand how it works?

User: Explain line by line please

Claude: Sure! Let me break it down:

**Line 1:** `function isValidEmail(email) {`
→ Creates a function named 'isValidEmail' that takes one parameter: the email string to validate

**Line 2:** `const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;`
→ Defines a regular expression pattern for email validation
→ This pattern checks for:
  - Some characters before @
  - An @ symbol
  - Some characters after @
  - A dot (.)
  - Some characters after the dot

**Line 3:** `return emailRegex.test(email);`
→ Uses the .test() method to check if the email matches the pattern
→ Returns true if valid, false if invalid

**Line 4:** `}`
→ Closes the function

Any questions about how this works?

User: Why that regex pattern? What does [^\s@]+ mean?

Claude: Great question! Let me explain the regex pattern in detail:

`[^\s@]+` means:
- `[...]` - a character set (match any character inside)
- `^` inside brackets means NOT
- `\s` means whitespace (spaces, tabs)
- `@` is the literal @ symbol
- So `[^\s@]` means "any character that is NOT whitespace or @"
- `+` means "one or more" of those characters

So `[^\s@]+` means "one or more characters that aren't spaces or @"

This ensures:
- No spaces in email
- No multiple @ symbols
- At least one character before and after @

The pattern `^[^\s@]+@[^\s@]+\.[^\s@]+$` means:
- `^` start of string
- characters before @
- one @ symbol
- characters between @ and .
- one . (dot)
- characters after .
- `$` end of string

Make sense now?

User: Yes! Apply it

Claude: [Uses Write tool to create the function]
✅ Email validation function created!
```

### Example 2: Understanding Existing Code

```
User: Explain this code to me [shows React component]

Claude: I'll read the file and explain it line by line...

[Reads the file]

This is a React component. Let me explain what each part does:

**Lines 1-3: Imports**
→ Line 1: Imports React library
→ Line 2: Imports useState hook for managing state
→ Line 3: Imports a custom CSS file for styling

**Lines 5-7: Component Declaration**
→ Declares a functional component named 'Counter'
→ Uses arrow function syntax

**Line 8: State Management**
→ `const [count, setCount] = useState(0);`
→ Creates a state variable 'count' starting at 0
→ 'setCount' is the function to update the count
→ This makes the component remember the count value

**Lines 10-15: Event Handler**
→ Function that runs when button is clicked
→ Increases count by 1 using setCount

**Lines 17-25: JSX Return**
→ The UI that gets displayed
→ Shows current count value
→ Button that triggers the handler when clicked

Which part would you like me to explain more?

User: Line 8 confuses me - what is useState?

Claude: Great question! `useState` is a React Hook. Let me explain:

**What it does:**
- Lets your component "remember" data between renders
- When you update the state, React re-renders the component with new value

**The syntax:**
```javascript
const [value, setValue] = useState(initialValue);
```

- `value` - the current state value (like a variable)
- `setValue` - function to change the value
- `initialValue` - what it starts as (0 in our case)

**Why we need it:**
- Regular variables reset every time component renders
- State variables persist and trigger re-renders when changed

**In our example:**
```javascript
const [count, setCount] = useState(0);
```
- `count` is the current number (starts at 0)
- `setCount(5)` would change count to 5 and re-render
- `setCount(count + 1)` increases by 1

Think of it like a special variable that React watches.

Is that clearer?

User: Yes! Much clearer now

Claude: Awesome! Do you have questions about any other lines, or do you understand the full component now?
```

### Example 3: Quick Review for Experienced User

```
User: Add error handling to the API call

Claude: I'll add try-catch error handling. Here's the code:

```javascript
try {
  const response = await fetch('/api/data');
  const data = await response.json();
  return data;
} catch (error) {
  console.error('API call failed:', error);
  throw error;
}
```

This wraps the API call in try-catch to handle network errors. The catch block logs the error and re-throws it.

Need line-by-line explanation, or is this clear?

User: Clear, apply it

Claude: [Applies the code]
✅ Error handling added!
```

## Best Practices for Explanations

### 1. Start with Context
Always begin with what the code does at a high level before diving into lines.

### 2. Use Plain English
Avoid jargon. If you must use a technical term, explain it.

**❌ Bad:** "This uses array destructuring with the spread operator"
**✅ Good:** "This breaks apart the array into individual items using `...` syntax"

### 3. Show Examples
When explaining a concept, show a simple example:

```
The reduce() method combines array items into a single value.

Example:
[1, 2, 3].reduce((sum, num) => sum + num, 0)
→ Starts at 0
→ 0 + 1 = 1
→ 1 + 2 = 3
→ 3 + 3 = 6
Result: 6
```

### 4. Explain WHY, Not Just WHAT
Users learn better when they understand the reasoning.

**❌ Bad:** "This uses a Set to store values"
**✅ Good:** "This uses a Set instead of an array because Sets automatically remove duplicates, which is exactly what we need here"

### 5. Invite Questions Proactively
Don't wait for confusion - ask if things are clear:
- "Make sense so far?"
- "Any questions about this part?"
- "This is the tricky bit - need more explanation?"

### 6. Connect to User's Knowledge
If possible, relate to concepts they already know:
- "This is like a for loop, but more concise"
- "Similar to what we did in Header.vue yesterday"

### 7. Use Visual Aids
Use arrows, brackets, and formatting to show flow:

```
items.map(item => item.name)
      ↓
   for each item
      ↓
   extract the name property
      ↓
   return array of names
```

## Handling Different Code Types

### Frontend (React, Vue, HTML/CSS)
- Explain component lifecycle
- Show how props/state flow
- Describe visual results ("This makes the button blue")

### Backend (Node, Python, APIs)
- Explain request/response flow
- Show data transformations
- Mention security implications

### Database Queries
- Show what data is being fetched
- Explain joins visually
- Mention performance implications

### Config Files
- Explain what each setting does
- Show effect of changing values
- Mention defaults

## Common Questions and How to Answer

### "Why did you choose this approach?"
- List alternatives considered
- Explain trade-offs
- Show why this is best for this situation

### "What does [technical term] mean?"
- Define it simply
- Show an example
- Compare to similar concepts

### "Can we do it differently?"
- Say yes! Show alternatives
- Explain pros/cons of each
- Let user choose if reasonable

### "Is this the best way?"
- Depends on context
- Explain optimization opportunities
- Mention when to optimize vs. when simple is better

## Code Approval Signals

### User Understands (Proceed):
- "got it"
- "makes sense"
- "okay"
- "apply it"
- "clear"
- "I understand now"
- "thanks, proceed"

### User Needs More Info (Don't Proceed):
- "wait"
- "can you explain..."
- "I don't understand..."
- "what about..."
- "why..."
- Questions about any line

### User Wants Alternative (Discuss):
- "can we do it differently"
- "is there another way"
- "what if we..."

## Integration with Other Tools

### With code-reviewer Skill
- code-explainer: BEFORE writing (education focus)
- code-reviewer: AFTER writing (quality focus)

### With File Operations
- Read code → Explain it
- Explain new code → Get approval → Write it
- Edit code → Explain changes → Apply edit

### With Testing
- Write test → Explain what it tests → Apply
- Test fails → Explain why → Fix and explain

## Measuring Success

The skill is working well when:
- ✅ User says "I learned something"
- ✅ User asks fewer questions over time (learning)
- ✅ User can explain code back to you
- ✅ User suggests their own solutions
- ✅ User approves code confidently

## Tips for Effective Use

### For Users:
1. **Don't be shy about asking questions** - that's what this is for!
2. **Ask about specific lines** - "Why line 5?" is better than "I'm confused"
3. **Request examples** - "Can you show an example of how this works?"
4. **Pace yourself** - It's okay to understand one concept at a time
5. **Test your understanding** - Try to explain it back to Claude

### For Claude:
1. **Check understanding regularly** - Don't assume they're following
2. **Adjust explanation depth** - Watch their responses to gauge level
3. **Be patient with questions** - Every question is a learning opportunity
4. **Celebrate understanding** - Acknowledge when they get it
5. **Encourage experimentation** - Suggest they try modifying the code

## Quick Reference

```
┌─────────────────────────────────────────────┐
│         Code Explainer Workflow              │
├─────────────────────────────────────────────┤
│                                             │
│  1. Show Code Block (don't apply yet)      │
│                                             │
│  2. High-Level Overview                     │
│     → What it does                          │
│     → Why this approach                     │
│                                             │
│  3. Ask: "Need line-by-line explanation?"  │
│                                             │
│  4a. If YES:                                │
│      → Explain each line                    │
│      → Invite questions                     │
│      → Answer questions                     │
│      → Get approval                         │
│                                             │
│  4b. If NO:                                 │
│      → Proceed to apply                     │
│                                             │
│  5. Apply Code (only after approval)        │
│                                             │
└─────────────────────────────────────────────┘
```

## Example Templates

### Template: Proposing New Code
```
I'll create [feature]. Here's the code:

[CODE BLOCK]

This [high-level explanation].

Would you like me to:
1. Explain it line by line
2. Explain specific parts
3. Apply it (you understand it)
```

### Template: Line Explanation
```
Let me explain each line:

Line X: [code]
→ [what it does]
→ [why it's needed]

Line Y: [code]
→ [what it does]
→ [important detail]

Any questions?
```

### Template: Answering Questions
```
Great question about [topic]!

[Explanation with examples]

Does that make it clearer? Need more details?
```

---

**Remember:** The goal is not just to write code, but to ensure the user understands and learns from every change. Code they understand is code they can maintain and improve.
