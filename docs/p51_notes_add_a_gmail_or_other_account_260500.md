  
  Adding a Gmail account. Sidebar → Connections (/app/connections). The page lists your connected accounts and has a "Connect a Gmail account" button. Click it → frontend POSTs /gmail/oauth/start → backend returns a Google consent URL → browser redirects you to Google → you sign in to whichever Google account you want to add → Google redirects back to /app/connections?connected=<email> and the account appears in the list with status: active. Repeat the button for a second Gmail; pick a different Google account in Google's chooser. Once it's connected, the Service selector in any type-3/5/6 workflow form shows gmail as an option, and the account dropdown then comes from /gmail/accounts (your real connected addresses, not the hardcoded list).

  The OAuth scopes the connect flow requests cover read + compose + send + calendar.readonly, so a single connect handles all current Gmail-flavored features. (If we ever add another scope later, you'd need to reconnect the same account once to re-grant.)
                                                                                                              
  The three Apple Mail labels. Yes, hardcoded — same place I cited: MAIL_ACCOUNTS at WorkflowConfigForm.tsx:26-30. They're a developer-time constant baked into the frontend. Nothing else in the codebase enumerates Apple Mail accounts; the runner just passes whichever string you picked straight to the Apple Mail MCP server.
                                      
  Pin noted on the user_email_accounts redesign — happy to plan that whenever you want to pick it back up. The Apple-Mail enumeration piece is interesting because Mail.app does expose its account list via AppleScript, so we could either

  (a) add a UI form where the user types account-name/type/etc. like you described, or 

  (b) have the MCP server enumerate Mail.app's actual configured accounts and surface them via an endpoint analogous to /gmail/accounts. Option (b) is less typing for the user but only works on the local Mac; option (a) generalizes to remote Apple Mail-less clients. We can decide that when you unpin.
