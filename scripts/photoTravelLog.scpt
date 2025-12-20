#!/usr/bin/osascript
-- SkiCycleRun Photo Travel Log Generator
-- Exports photo metadata (location, date/time) from Apple Photos as JSON
-- Usage: osascript photoTravelLog.scpt [output_json_path]

use AppleScript version "2.4"
use scripting additions
use framework "Foundation"

on run argv
	-- Get output path from argument or use default
	if (count of argv) > 0 then
		set outputPath to item 1 of argv
	else
		set envLibRoot to my resolveEnv("SKICYCLERUN_LIB_ROOT")
		if envLibRoot is not "" then
			set outputPath to my appendPath(envLibRoot, "logs/travel_log.json")
		else
			set outputPath to "/Volumes/MySSD/ImageLib/travel_log.json"
		end if
	end if
	log "Travel log will be saved to: " & outputPath
	
	-- Create temp directory for EXIF extraction
	set tempDir to do shell script "mktemp -d"
	log "Using temp directory: " & tempDir
	
	tell application "Photos"
		activate
		
		-- Get list of all album names
		set albumList to name of albums
		
		if (count of albumList) is 0 then
			display dialog "No albums found in Photos library" buttons {"OK"} default button 1
			return
		end if
		
		-- Present album selector dialog
		set selectedAlbums to choose from list albumList with prompt "Select albums for travel log:" with multiple selections allowed
		
		-- User cancelled
		if selectedAlbums is false then
			log "Travel log cancelled by user"
			do shell script "rm -rf " & quoted form of tempDir
			return
		end if
		
		log "Processing " & (count of selectedAlbums) & " albums..."
		
		-- Initialize JSON structure
		set jsonData to "{"
		set jsonData to jsonData & "\"travel_log\": {"
		set jsonData to jsonData & "\"generated_at\": \"" & my getCurrentTimestamp() & "\","
		set jsonData to jsonData & "\"total_albums\": " & (count of selectedAlbums) & ","
		set jsonData to jsonData & "\"albums\": ["
		
		set albumCounter to 0
		
		-- Process each selected album
		repeat with albumName in selectedAlbums
			set albumCounter to albumCounter + 1
			set currentAlbum to first album whose name is (albumName as text)
			set photoItems to media items of currentAlbum
			set photoCount to count of photoItems
			
			log "Processing album: " & albumName & " (" & photoCount & " photos)"
			
			-- Start album JSON
			if albumCounter > 1 then
				set jsonData to jsonData & ","
			end if
			
			set jsonData to jsonData & "{"
			set jsonData to jsonData & "\"album_name\": " & my escapeJSON(albumName as text) & ","
			set jsonData to jsonData & "\"photo_count\": " & photoCount & ","
			set jsonData to jsonData & "\"photos\": ["
			
			set photoCounter to 0
			
			-- Process each photo in album
			repeat with photoItem in photoItems
				set photoCounter to photoCounter + 1
				
				try
					-- Get photo metadata
					set photoFilename to filename of photoItem
					set photoDate to date of photoItem
					
					-- Export photo temporarily to extract EXIF GPS data
					-- Photos may change the extension on export, so we'll find the actual file
					with timeout of 30 seconds
						export {photoItem} to (POSIX file tempDir as alias) with metadata
					end timeout
					
					-- Find the exported file (Photos may rename it)
					set exportedFiles to do shell script "ls -t " & quoted form of tempDir & " | head -1"
					set tempPhotoPath to tempDir & "/" & exportedFiles
					
					log "Exported: " & photoFilename & " -> " & exportedFiles
					
					-- Extract GPS coordinates using exiftool
					set gpsData to my extractGPSData(tempPhotoPath)
					
					-- Start photo JSON
					if photoCounter > 1 then
						set jsonData to jsonData & ","
					end if
					
					set jsonData to jsonData & "{"
					set jsonData to jsonData & "\"filename\": " & my escapeJSON(photoFilename) & ","
					set jsonData to jsonData & "\"date\": " & my escapeJSON(my formatDate(photoDate)) & ","
					set jsonData to jsonData & "\"timestamp\": " & my escapeJSON(photoDate as string) & ","
					set jsonData to jsonData & gpsData
					set jsonData to jsonData & "}"
					
					-- Clean up temp file
					do shell script "rm -f " & quoted form of tempPhotoPath
					
				on error errMsg
					log "Warning: Could not process photo " & photoCounter & " in " & albumName & ": " & errMsg
				end try
				
			end repeat
			
			-- Close photos array and album object
			set jsonData to jsonData & "]"
			set jsonData to jsonData & "}"
			
		end repeat
		
		-- Close JSON structure
		set jsonData to jsonData & "]"
		set jsonData to jsonData & "}"
		set jsonData to jsonData & "}"
		
	end tell
	
	-- Clean up temp directory
	do shell script "rm -rf " & quoted form of tempDir
	
	-- Write JSON to file
	try
		my ensureParentDirectory(outputPath)
		-- Use do shell script instead of AppleScript file access
		do shell script "cat > " & quoted form of outputPath & " << 'EOF'
" & jsonData & "
EOF"
		
		log "✓ Travel log saved to: " & outputPath
		display dialog "Travel log generated successfully!" & return & return & "Output: " & outputPath buttons {"OK"} default button 1
		
	on error errMsg
		log "✗ ERROR writing travel log: " & errMsg
		display dialog "Error writing travel log:" & return & errMsg buttons {"OK"} default button 1
	end try
	
end run

on resolveEnv(varName)
	try
		set value to do shell script "printenv " & quoted form of varName
		if value is "" then
			return ""
		else
			return my stripTrailingSlash(value)
		end if
	on error
		return ""
	end try
end resolveEnv

on appendPath(basePath, child)
	if basePath ends with "/" then
		return basePath & child
	else
		return basePath & "/" & child
	end if
end appendPath

on stripTrailingSlash(somePath)
	if somePath ends with "/" then
		return text 1 thru -2 of somePath
	else
		return somePath
	end if
end stripTrailingSlash

on ensureParentDirectory(filePath)
	set parentDir to do shell script "dirname " & quoted form of filePath
	do shell script "mkdir -p " & quoted form of parentDir
end ensureParentDirectory

-- Extract GPS data from image file using exiftool
on extractGPSData(filePath)
	try
		-- Use exiftool with -n flag for numeric GPS coordinates
		set gpsOutput to do shell script "/opt/homebrew/bin/exiftool -GPSLatitude -GPSLongitude -n -s3 " & quoted form of filePath & " 2>/dev/null"
		
		-- exiftool -s3 outputs just values, one per line
		set coordLines to paragraphs of gpsOutput
		
		if (count of coordLines) ≥ 2 then
			set lat to item 1 of coordLines
			set lon to item 2 of coordLines
			
			-- Check if we got actual numbers (not empty)
			if lat is not "" and lon is not "" and lat is not "-" and lon is not "-" then
				return "\"location\": {\"latitude\": " & lat & ", \"longitude\": " & lon & "}"
			end if
		end if
		
		return "\"location\": null"
		
	on error errMsg
		log "GPS extraction error for " & filePath & ": " & errMsg
		return "\"location\": null"
	end try
end extractGPSData

-- Format date as ISO 8601 string (local time)
on formatDate(theDate)
	set y to year of theDate as string
	set m to text -2 thru -1 of ("00" & (month of theDate as integer))
	set d to text -2 thru -1 of ("00" & day of theDate)
	set hh to text -2 thru -1 of ("00" & hours of theDate)
	set mm to text -2 thru -1 of ("00" & minutes of theDate)
	set ss to text -2 thru -1 of ("00" & seconds of theDate)
	return y & "-" & m & "-" & d & "T" & hh & ":" & mm & ":" & ss
end formatDate

-- Get current timestamp
on getCurrentTimestamp()
	return my formatDate(current date)
end getCurrentTimestamp

-- Escape JSON string (handle quotes and special chars)
on escapeJSON(txt)
	set txt to txt as text
	
	-- Replace backslash first
	set AppleScript's text item delimiters to "\\"
	set txtItems to text items of txt
	set AppleScript's text item delimiters to "\\\\"
	set txt to txtItems as string
	
	-- Replace double quotes
	set AppleScript's text item delimiters to "\""
	set txtItems to text items of txt
	set AppleScript's text item delimiters to "\\\""
	set txt to txtItems as string
	
	-- Replace newlines
	set AppleScript's text item delimiters to return
	set txtItems to text items of txt
	set AppleScript's text item delimiters to "\\n"
	set txt to txtItems as string
	
	-- Replace tabs
	set AppleScript's text item delimiters to tab
	set txtItems to text items of txt
	set AppleScript's text item delimiters to "\\t"
	set txt to txtItems as string
	
	set AppleScript's text item delimiters to ""
	return "\"" & txt & "\""
end escapeJSON
