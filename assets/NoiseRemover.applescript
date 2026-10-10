-- Noise Remover: stay-open applet that runs the local server and opens the web UI.
-- Built by assets/build_app.sh — edit this file, then rebuild.
--
-- The applet must never block: startup waiting happens in the idle handler so the
-- app stays responsive (blocking here is what makes macOS report "Not Responding").
-- Mutable state uses globals, not properties, so the signed bundle is never rewritten.

global projectDir, serverURL, pendingOpen, waited

on run
	-- The app lives in the project folder, so the project is the app's parent directory.
	set projectDir to do shell script "dirname " & quoted form of POSIX path of (path to me)
	set serverURL to "http://localhost:8765"
	set pendingOpen to false
	set waited to 0
	showPage()
end run

-- Clicking the Dock icon while running reopens the page.
on reopen
	showPage()
end reopen

on showPage()
	if isUp() then
		openBrowser()
	else if not pendingOpen then
		launchServer()
		set pendingOpen to true
		set waited to 0
	end if
end showPage

-- `open location` silently does nothing from an ad-hoc-signed applet, so use /usr/bin/open.
on openBrowser()
	do shell script "open " & quoted form of serverURL
end openBrowser

on isUp()
	try
		-- Hits an API path (404 is fine) so health checks don't look like page views in server.log.
		do shell script "curl -s -o /dev/null --max-time 1 " & serverURL & "/api/jobs/health"
		return true
	on error
		return false
	end try
end isUp

on launchServer()
	-- Redirect the whole subshell's stdio so `do shell script` returns immediately
	-- instead of waiting on a background process that still holds its output pipe.
	do shell script "(cd " & quoted form of projectDir & " && exec nohup .venv/bin/uvicorn app:app --host 127.0.0.1 --port 8765) > " & quoted form of (projectDir & "/server.log") & " 2>&1 < /dev/null &"
end launchServer

on idle
	if pendingOpen then
		if isUp() then
			set pendingOpen to false
			openBrowser()
		else
			set waited to waited + 1
			if waited > 90 then
				set pendingOpen to false
				display dialog "Noise Remover failed to start. Check server.log in:" & return & projectDir buttons {"OK"} default button 1 with icon stop
			end if
		end if
		return 1
	end if
	return 60
end idle

-- Quitting the app (Dock → Quit, or ⌘Q) stops the server, even if it is still starting up.
on quit
	try
		do shell script "pkill -f 'uvicorn app:app --host 127.0.0.1 --port 8765'"
	end try
	continue quit
end quit
