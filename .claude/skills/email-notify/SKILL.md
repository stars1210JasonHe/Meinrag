---
name: email-notify
description: Automatically send development updates, errors, screenshots and results via email for remote development. Use when user requests email notification, is working remotely, or needs to receive development results outside of the IDE.
allowed-tools: Bash, Read, Glob
---

# Email Notification Skill

Automatically send development updates via email for remote development scenarios (e.g., using Happy app on smartphone).

## When to Use This Skill

Automatically use this skill when:
- User explicitly requests "email me", "send email", "notify me via email"
- User is working remotely and needs results outside IDE
- After completing significant development tasks (build, deploy, updates)
- When errors occur that user needs to know about immediately
- User asks to "check results remotely" or "send me the results"

## How Remote Development Works

User scenario:
- Uses Happy app on smartphone to control Claude Code
- No access to IDE or file explorer
- Can only communicate via chat
- **Needs email to see screenshots, errors, and results**

## Email Script Location

The email notification script is at: `email-notify.py`

Configuration file: `email-config.json` (user must set this up first)

## Available Notification Types

| Type | When to Use | Icon |
|------|-------------|------|
| `success` | Successful operations, updates completed | ✅ |
| `error` | Build failures, runtime errors | ❌ |
| `warning` | Non-critical issues, deprecations | ⚠️ |
| `info` | General information, status updates | ℹ️ |
| `build` | Build process results | 🔨 |
| `deploy` | Deployment status and results | 🚀 |
| `test` | Test execution results | 🧪 |
| `debug` | Debugging information, investigations | 🐛 |

## Command Format

```bash
python email-notify.py [type] --title "Title" [options]
```

### Required Parameters
- `type`: Notification type (success, error, warning, etc.)
- `--title`: Email subject title

### Optional Parameters
- `--description`: Detailed description
- `--status`: Status message
- `--screenshot`: Path to screenshot file
- `--log`: Path to log file
- `--changes`: List of changes made
- `--errors`: List of error messages
- `--next-steps`: List of recommended next steps
- `--files`: List of affected file paths

## Common Usage Patterns

### Pattern 1: Frontend Update Complete

After making frontend changes:

1. Take screenshot using screenshot-debug skill
2. Send email with screenshot:

```bash
python email-notify.py success \
  --title "Frontend Update Complete" \
  --description "Updated Chinese translations" \
  --screenshot "screenshots/display/[latest].png" \
  --changes "Header translated" "Footer translated" "Hero stats fixed" \
  --next-steps "Review screenshot" "Test language switcher"
```

### Pattern 2: Build Error Report

When build fails:

1. Capture error output
2. Send detailed error email:

```bash
python email-notify.py error \
  --title "Build Failed" \
  --description "npm run build encountered errors" \
  --errors "[error message 1]" "[error message 2]" \
  --files "[file path:line number]" \
  --next-steps "Fix [specific issue]" "Rebuild"
```

### Pattern 3: Deployment Success

After successful deployment:

1. Take final screenshot
2. Send success notification:

```bash
python email-notify.py deploy \
  --title "Deployed to Production" \
  --description "Website is now live" \
  --status "✅ Deployment successful" \
  --screenshot "screenshots/deploy/[timestamp].png" \
  --changes "[list of changes]" \
  --next-steps "Visit [URL]" "Test all features"
```

### Pattern 4: Debug Investigation

When debugging issues:

1. Take debug screenshot
2. Capture relevant logs
3. Send debug report:

```bash
python email-notify.py debug \
  --title "[Issue description]" \
  --description "[What you found]" \
  --screenshot "screenshots/debug/[timestamp].png" \
  --errors "[error messages from console]" \
  --logs "[relevant output]" \
  --next-steps "[proposed fix]"
```

## Step-by-Step Workflow

### When User Requests Email Notification

**User says:** "Send me an email with the results" or "Email me the screenshot"

**You should:**

1. **Determine what to send**:
   - If recent frontend change: Use screenshot-debug skill to get screenshot
   - If build/deploy: Collect relevant logs
   - If error occurred: Gather error messages

2. **Prepare notification details**:
   - Choose appropriate type (success, error, etc.)
   - Write clear title
   - List all changes made
   - Include relevant files
   - Suggest next steps

3. **Find latest screenshot** (if applicable):
   ```bash
   # List latest screenshots
   ls -t screenshots/display/ | head -1
   # or
   ls -t screenshots/debug/ | head -1
   ```

4. **Send email**:
   ```bash
   python email-notify.py [type] --title "[title]" [options]
   ```

5. **Confirm to user**:
   ```
   ✅ Email sent successfully!
   📧 Subject: [subject]
   📎 Attachments: [list]

   Please check your inbox.
   ```

## Example Conversations

### Example 1: After Translation Update

```
User: I updated all the translations to Chinese, send me an email to verify
Claude:
  1. [Uses screenshot-debug skill to take screenshot]
  2. [Analyzes screenshot]
  3. [Sends email]

✅ Email sent successfully!
📧 Subject: ✅ SUCCESS: Chinese Translation Complete
📎 Attachments: screenshot.png (1.2 MB)

Email contains:
- Screenshot of the homepage in Chinese
- List of changes: Header, Footer, Hero stats, Practice cards
- Next steps: Review screenshot, test language switcher

Please check your inbox!
```

### Example 2: Build Failure

```
User: Build failed, email me the error details
Claude:
  1. [Reads build logs]
  2. [Identifies errors]
  3. [Sends email]

✅ Error report sent!
📧 Subject: ❌ ERROR: Build Failed - Type Error
📋 Contains:
- Error messages from build output
- Affected files with line numbers
- Suggested fixes

Check your email for details.
```

### Example 3: Deployment Notification

```
User: Deployed to Firebase, send me confirmation
Claude:
  1. [Takes deploy screenshot]
  2. [Verifies deployment]
  3. [Sends success email]

✅ Deployment confirmation sent!
📧 Subject: 🚀 DEPLOY: Successfully Deployed to Firebase
📎 Screenshot attached
🔗 Live URL included

Your deployment is complete!
```

## Email Content Recommendations

### For Frontend Updates

Include:
- **Title**: "Frontend Update: [specific change]"
- **Screenshot**: Latest from screenshots/display/
- **Changes**: List every UI change made
- **Status**: "Update successful" or "Needs review"
- **Next Steps**: "Review screenshot", "Test functionality", "Deploy if looks good"

### For Build Errors

Include:
- **Title**: "Build Failed: [error type]"
- **Errors**: Full error messages from console
- **Files**: Exact file paths and line numbers
- **Description**: What was being built when it failed
- **Next Steps**: Specific fix instructions

### For Deployment

Include:
- **Title**: "Deployed to [platform]"
- **Status**: "✅ Live" or "❌ Failed"
- **Screenshot**: Final production screenshot
- **Changes**: Complete changelog
- **Next Steps**: "Visit [URL]", "Test [features]", "Monitor [metrics]"

### For Debug Reports

Include:
- **Title**: "[Issue] - Investigation Results"
- **Screenshot**: Debug screenshot showing issue
- **Logs**: Relevant console output
- **Errors**: Any error messages
- **Description**: What you discovered
- **Next Steps**: Proposed fix with steps

## Important: Configuration Check

Before sending email, check if `email-config.json` exists:

```bash
# Check if config exists
if [ ! -f email-config.json ]; then
  echo "⚠️  Email not configured yet"
  echo "Run: python email-notify.py success --title 'Test' to create config template"
  echo "Then edit email-config.json with your SMTP settings"
fi
```

If config doesn't exist, inform user:
```
⚠️  Email notifications not set up yet.

To enable email notifications:
1. Run: python email-notify.py success --title "Test"
2. Edit the generated email-config.json file
3. Add your Gmail credentials

See EMAIL_NOTIFY_SETUP.md for detailed instructions.
```

## Error Handling

If email sending fails:

1. **Check configuration**:
   ```bash
   cat email-config.json
   ```

2. **Common issues**:
   - Wrong password (need App Password for Gmail)
   - Wrong SMTP server
   - Network connection issues

3. **Inform user**:
   ```
   ❌ Failed to send email

   Possible issues:
   - Email not configured (check email-config.json)
   - Wrong SMTP credentials
   - Network connection problem

   See EMAIL_NOTIFY_SETUP.md for troubleshooting.
   ```

## Integration with Other Skills

### With screenshot-debug Skill

Always combine with screenshot-debug when sending visual updates:

```
User: Update complete, send me email
Claude:
  1. [screenshot-debug skill: takes screenshot]
  2. [email-notify skill: sends email with screenshot]
```

### Standalone Email

When no screenshot needed (errors, logs):

```
User: Email me the build logs
Claude:
  1. [Reads recent build output]
  2. [email-notify skill: sends log summary]
```

## Best Practices

1. **Always include context**: User is remote, can't see your screen
2. **Be specific in titles**: "Frontend Update" not "Update"
3. **Attach screenshots when relevant**: Visual verification is key
4. **List all changes**: Don't assume user knows what changed
5. **Suggest next steps**: Remote user needs guidance
6. **Keep attachments reasonable**: Compress large screenshots
7. **Confirm send success**: Always tell user email was sent
8. **Check config first**: Verify setup before attempting to send

## Security Reminders

- Never include `email-config.json` in git commits
- Always use App Passwords, never real passwords
- Remind user to keep credentials secure
- Config file is in .gitignore automatically

## Quick Reference

```bash
# Success notification with screenshot
python email-notify.py success \
  --title "Update Complete" \
  --screenshot "path/to/screenshot.png" \
  --changes "change 1" "change 2"

# Error notification
python email-notify.py error \
  --title "Build Failed" \
  --errors "error message" \
  --files "file.ts:42"

# Deploy notification
python email-notify.py deploy \
  --title "Deployed Successfully" \
  --status "Website is live" \
  --screenshot "screenshot.png"

# Debug notification
python email-notify.py debug \
  --title "Investigating Issue" \
  --logs "console output" \
  --next-steps "fix suggestion"
```

---

**This skill enables fully remote development through email notifications!** 📱✉️