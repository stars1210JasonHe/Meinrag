# Code Explainer Skill - Quick Start Guide

## What This Skill Does

Interactive code explanation that helps you **understand code before it's applied**. Instead of just writing code, Claude will:

1. ✍️ Show you the code first
2. 📖 Explain what it does
3. 🔍 Walk through it line by line (if you want)
4. ❓ Answer your questions
5. ✅ Apply it only after you approve

## How to Use It

### Automatic Triggering

The skill activates when you say:
- "Explain this code to me"
- "Help me understand this"
- "Walk me through the code"
- "What does each line do?"
- "Review and explain before applying"

### Interactive Flow

**1. Claude shows you code:**
```javascript
function calculateTotal(items) {
  return items.reduce((sum, item) => sum + item.price, 0);
}
```

**2. Claude asks if you want explanation:**
```
Would you like me to:
1. Explain it line by line
2. Explain only specific parts
3. Apply it directly (you already understand)
```

**3. You choose:**
- Say **"line by line"** → Full explanation of every line
- Say **"line 2 only"** → Explain just that part
- Say **"apply it"** → Skip explanation, you understand

**4. Claude explains:**
```
Line 1: function calculateTotal(items) {
→ Creates a function that accepts an array of items

Line 2: return items.reduce((sum, item) => sum + item.price, 0);
→ Uses reduce() to sum all item prices
→ Starts at 0, adds each item.price to the total
```

**5. You ask questions:**
- "Why reduce()?"
- "What's an arrow function?"
- "Line 2 confuses me"

**6. Claude answers your questions**

**7. When you understand:**
- Say **"got it"** or **"apply it"**
- Claude applies the code

## Example Conversations

### Example 1: Learning a New Pattern

**You:** Add a function to sort items by price

**Claude:** I'll create a sort function. Here's the code:

```javascript
function sortByPrice(items) {
  return [...items].sort((a, b) => a.price - b.price);
}
```

This returns a sorted copy of the items array, ordered by price (lowest to highest).

Need me to explain it line by line?

**You:** Yes please

**Claude:** Sure!

**Line 1:** `function sortByPrice(items) {`
→ Declares a function that accepts an items array

**Line 2:** `return [...items].sort((a, b) => a.price - b.price);`

Let me break this down:
- `[...items]` creates a copy of the array (important!)
- `.sort()` sorts the copied array
- `(a, b) => a.price - b.price` is the comparison function
  - If a.price < b.price, returns negative → a comes first
  - If a.price > b.price, returns positive → b comes first

The reason we copy first: `.sort()` modifies the original array. By copying with `[...]`, we keep the original untouched.

Questions?

**You:** Why copy? Can't we just sort directly?

**Claude:** Great question! We *could* sort directly like this:

```javascript
items.sort((a, b) => a.price - b.price);
```

But this would **change the original array**. Here's why that's usually bad:

**Without copying:**
```javascript
const original = [{price: 3}, {price: 1}];
sortByPrice(original);
console.log(original); // [{price: 1}, {price: 3}] - CHANGED!
```

**With copying:**
```javascript
const original = [{price: 3}, {price: 1}];
const sorted = sortByPrice(original);
console.log(original); // [{price: 3}, {price: 1}] - UNCHANGED!
console.log(sorted);   // [{price: 1}, {price: 3}] - SORTED!
```

This follows the principle of "immutability" - don't modify the input, return a new result. It prevents bugs where you accidentally change data elsewhere in your app.

Make sense?

**You:** Yes! That's really helpful. Apply it

**Claude:** ✅ Function created! The items array will stay untouched and you'll get a sorted copy.

---

### Example 2: Quick Review

**You:** Add error handling to the API call

**Claude:** I'll wrap it in try-catch:

```javascript
try {
  const data = await fetchData();
  return data;
} catch (error) {
  console.error('Fetch failed:', error);
  return null;
}
```

This catches any fetch errors, logs them, and returns null instead of crashing.

Need line-by-line explanation or is this clear?

**You:** Clear, apply it

**Claude:** ✅ Error handling added!

---

## Tips for Best Results

### ✅ DO:
- Ask about specific lines: "What does line 3 do?"
- Request examples: "Can you show an example?"
- Admit confusion: "I don't understand the arrow function"
- Ask for alternatives: "Is there another way to do this?"
- Test your understanding: Try to explain it back

### ❌ DON'T:
- Say "I don't get it" without specifics
- Skip explanations out of embarrassment - this is for learning!
- Approve code you don't understand - ask more questions!

## Understanding Signals

### When You Understand (Claude will apply code):
- "got it"
- "makes sense"
- "apply it"
- "okay, proceed"
- "clear now"

### When You Don't (Claude will explain more):
- "wait"
- "can you explain..."
- "I'm confused about..."
- Any question about the code

## Levels of Explanation

Claude adjusts explanation depth based on your needs:

### Level 1: High-Level (default for simple code)
```
This function filters the array to only include active users.
```

### Level 2: Line-by-Line (default for complex code)
```
Line 1: Filter the users array
Line 2: Keep only items where status === 'active'
Line 3: Return the filtered array
```

### Level 3: Deep Dive (when you ask for more)
```
The filter() method:
- Creates a new array (doesn't modify original)
- Iterates through each element
- Keeps elements where callback returns true
- Time complexity: O(n)
- Alternatives: for loop, forEach with push
```

## Common Questions

**Q: Do I have to ask for line-by-line every time?**
A: No! If code is simple and you understand it, just say "apply it"

**Q: Can I ask Claude to explain existing code I don't understand?**
A: Yes! Say "explain this code to me" and point to the file

**Q: What if I only don't understand one line?**
A: Just ask about that line: "What does line 5 mean?"

**Q: Can I ask why Claude chose this approach?**
A: Absolutely! Ask "Why this way?" or "What are alternatives?"

**Q: What if the explanation is too technical?**
A: Say "Explain it more simply" or "I don't understand [term]"

## Restart Required

After creating this skill, **restart Claude Code** to activate it:
1. Close Claude Code completely
2. Reopen Claude Code
3. The skill will now auto-trigger when appropriate

## Combining with Other Skills

- **code-explainer** (this) → Before writing code (education)
- **code-reviewer** → After writing code (quality check)
- **screenshot-debug** → Visual verification
- **email-notify** → Send explanations via email

---

**Remember:** There are no stupid questions! The whole point is to learn and understand. Ask away! 🎓
