#!/usr/bin/osascript
-- SkiCycleRun Photo Exporter
-- Exports selected albums from Apple Photos to organized folders
-- Usage: osascript osxPhotoExporter.scpt [base_export_path]
-- Note: Set Photos→Preferences→General→Metadata: include GPS info

on run argv
	-- Get export base path from argument or use default
	if (count of argv) > 0 then
		set baseExportPath to item 1 of argv
	else
		-- Default to external SSD location
		set baseExportPath to "/Volumes/MySSD/skicyclerun.i2i/images/raw"
		
		-- Check if default path exists, if not offer to choose location
		try
			do shell script "test -d " & quoted form of baseExportPath
		on error
			-- Default path doesn't exist, ask user to choose
			set userChoice to button returned of (display dialog "Default export location not found:" & return & baseExportPath & return & return & "Would you like to choose a different location?" buttons {"Cancel", "Choose Folder"} default button 2)
			
			if userChoice is "Choose Folder" then
				set chosenFolder to choose folder with prompt "Select export destination folder:"
				set baseExportPath to POSIX path of chosenFolder
				-- Remove trailing slash if present
				if baseExportPath ends with "/" then
					set baseExportPath to text 1 thru -2 of baseExportPath
				end if
			else
				return
			end if
		end try
	end if
	
	log "Export destination: " & baseExportPath
	
	tell application "Photos"
		activate
		
		-- Get list of all album names
		set albumList to name of albums
		
		if (count of albumList) is 0 then
			display dialog "No albums found in Photos library" buttons {"OK"} default button 1
			return
		end if
		
		-- Present album selector dialog
		set selectedAlbums to choose from list albumList with prompt "Select albums to export:" with multiple selections allowed
		
		-- User cancelled
		if selectedAlbums is false then
			log "Export cancelled by user"
			return
		end if
		
		log "Selected " & (count of selectedAlbums) & " albums to export"
		
		set albumCounter to 0
		
		-- Export each selected album
		repeat with albumName in selectedAlbums
			set albumCounter to albumCounter + 1
			
			-- Get the album object
			set currentAlbum to first album whose name is (albumName as text)
			set photoCount to count of media items of currentAlbum
			
			log "Processing album " & albumCounter & ": " & albumName & " (" & photoCount & " photos)"
			
			-- Create album folder path (sanitize album name)
			set sanitizedName to my sanitizeFilename(albumName as text)
			set albumFolder to baseExportPath & "/" & sanitizedName
			
			-- Create folder if it doesn't exist
			my makeFolder(albumFolder)
			
			-- Export all photos in this album
			-- Export with ALL metadata preserved:
			--   with GPS = include GPS coordinates
			--   with metadata = preserve all EXIF/IPTC data
			--   without using originals = export as JPEG (not HEIC)
			with timeout of 600 seconds
				try
					export (get media items of currentAlbum) to (POSIX file albumFolder as alias) with metadata and GPS without using originals
					log "✓ Completed: " & albumName & " (" & photoCount & " photos exported)"
				on error errMsg
					log "✗ ERROR exporting album '" & albumName & "': " & errMsg
				end try
			end timeout
			
		end repeat
		
		log "Export complete! Processed " & (count of selectedAlbums) & " albums."
		display dialog "Export complete! " & (count of selectedAlbums) & " albums exported to:" & return & baseExportPath buttons {"OK"} default button 1
		
	end tell
end run

-- Create folder using shell command
on makeFolder(tPath)
	do shell script "mkdir -p " & quoted form of tPath
end makeFolder

-- Sanitize filename by removing invalid characters
on sanitizeFilename(fileName)
	set invalidChars to {"/", ":", "\\", "*", "?", "\"", "<", ">", "|"}
	set cleanName to fileName
	
	repeat with char in invalidChars
		set AppleScript's text item delimiters to char
		set nameItems to text items of cleanName
		set AppleScript's text item delimiters to "_"
		set cleanName to nameItems as string
	end repeat
	
	set AppleScript's text item delimiters to ""
	return cleanName
end sanitizeFilename

-- Get creation date from file metadata (for future use)
on getNewName(fileIn)
	try
		set xCmd to do shell script "/usr/bin/mdls -name kMDItemContentCreationDate " & quoted form of POSIX path of fileIn
		if xCmd is "(null)" then return ""
		return text 10 thru -1 of paragraph 1 of xCmd
	on error
		return ""
	end try
end getNewName
