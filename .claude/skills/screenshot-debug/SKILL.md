---
name: screenshot-debug
description: Automatically take screenshots using Playwright to verify frontend changes and debug visual issues. Organizes screenshots into debug, development, deploy, and display categories.
allowed-tools: Bash, Read, Write, Edit, Glob
---

# Screenshot Debug Skill

Automatically verify frontend changes by taking screenshots with Playwright and organizing them into categorized folders.

## When to Use This Skill

Use this skill whenever:/
- Making visual changes to the frontend (CSS, components, layouts)
- Debugging UI issues that need visual verification
- Verifying that translations/content are displaying correctly
- Before deploying to ensure everything looks correct
- When the user asks to "check", "verify", or "take a screenshot" of the website

## Instructions

### 1. Take Screenshots After Frontend Changes

After making any frontend changes (editing components, CSS, translations, etc.), automatically:

1. **Run the screenshot script** with the appropriate category:
   ```bash
   node screenshot.js [category]
   ```

   Categories:
   - `debug` - For debugging visual issues
   - `development` - For general development work (default)
   - `deploy` - Before deploying to production
   - `display` - For showcasing/presentation

2. **Read and analyze the screenshot** to verify changes

3. **Report findings** to the user with specific details about what's visible

### 2. Screenshot Script Location

The screenshot script is located at: `screenshot.js` in the project root.

### 3. Organized Screenshot Storage

Screenshots are automatically organized into:
```
screenshots/
├── debug/
├── development/
├── deploy/
└── display/
```

Each screenshot is timestamped: `YYYY-MM-DDTHH-MM-SS.png`

### 4. Verification Checklist

After taking a screenshot, check for:

**Text Content:**
- Is all text in the expected language?
- Are translations loading correctly?
- Any "undefined" or missing text?

**Components:**
- Are all components rendering?
- Correct number of cards/items showing?
- No layout breaks or overlaps?

**Visual Issues:**
- Colors and styling correct?
- Proper spacing and alignment?
- Responsive design working?

**Data Loading:**
- Practice area cards visible?
- Article cards visible?
- Images/icons loading?

### 5. Reporting Format

Always report screenshots to the user in this format:

```
✅ Screenshot taken: screenshots/[category]/[timestamp].png

Analysis:
- ✅ [What's working correctly]
- ❌ [What needs fixing]
- ⚠️ [Warnings or concerns]

Next steps:
- [What to fix/improve]
```

## Examples

### Example 1: After Translation Update

```
User: I updated the translations to Chinese
Assistant: Let me verify the translations by taking a screenshot.
[Runs: node screenshot.js development]
[Reads the screenshot]

✅ Screenshot saved: screenshots/development/2025-12-29T10-30-45.png

Analysis:
- ✅ Header shows "中国法律服务"
- ✅ Navigation in Chinese: "业务领域", "法律资讯", "联系我们"
- ❌ Stats section still in English: "Years Experience", "Cases Handled"
- ✅ Practice area cards loading with Chinese titles

Next steps:
- Fix the Hero component stats section to use Chinese text
```

### Example 2: Before Deployment

```
User: Ready to deploy?
Assistant: Let me take a final screenshot to verify everything.
[Runs: node screenshot.js deploy]
[Reads the screenshot]

✅ Screenshot saved: screenshots/deploy/2025-12-29T14-20-30.png

Analysis:
- ✅ All text in Chinese
- ✅ All 4 practice area cards loading
- ✅ Article cards displaying correctly
- ✅ No console errors
- ✅ Footer links and content correct

The website is ready for deployment! All visual elements are displaying correctly.
```

### Example 3: Debugging Visual Issue

```
User: The practice area cards aren't showing
Assistant: Let me debug this with a screenshot.
[Runs: node screenshot.js debug]
[Reads the screenshot and checks console output]

❌ Screenshot saved: screenshots/debug/2025-12-29T09-15-20.png

Analysis:
- ❌ 0 practice cards found on page
- ⚠️ Console shows: "Vue Router warn: No match found for /mock/practices-zh.json"
- ✅ Other sections rendering correctly

Issue identified: Vue Router is intercepting JSON file requests. Need to change from $fetch to direct imports.
```

## Best Practices

1. **Always take screenshots after visual changes** - Don't assume it worked
2. **Use appropriate categories** - debug for debugging, deploy before deploying
3. **Read the screenshot** - Don't just take it, analyze it
4. **Check console output** - Playwright captures console messages and errors
5. **Report specific details** - Tell the user exactly what you see
6. **Suggest fixes** - If you find issues, propose solutions

## Technical Details

### Screenshot Script Features

- **Full page screenshots** - Captures entire scrollable page
- **Console logging** - Shows browser console messages
- **Error detection** - Captures JavaScript errors
- **Network idle** - Waits for all resources to load
- **Element counting** - Verifies components are rendering

### Troubleshooting

If screenshots fail:
1. Check if dev server is running on localhost:3002
2. Verify Playwright is installed: `npm install -D playwright @playwright/test`
3. Install browser: `npx playwright install chromium`
4. Check screenshot.js exists and is executable

## Related Files

- `screenshot.js` - Main screenshot script
- `screenshots/` - Screenshot storage directory
- Dev server typically runs on `http://localhost:3002`
