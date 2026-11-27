-- VISPA MP bridge for the free edition of DaVinci Resolve.
-- Workspace > Scripts lists Lua only on this machine, so this file is the menu entry.
-- Run it once per Resolve session. It opens no window (a script window is a
-- Studio feature) and keeps answering VISPA MP through cache/resolve_link until
-- Resolve closes, VISPA MP sends "stop", or the script is run again.

local MAILBOX = [[__MAILBOX__]]
local AUTOMATIC = "vispa-mp"
local MARKER_NAMES = { Green = "Page", Blue = "Core", Cyan = "Extra" }
-- VISPA MP asks for this version: an older copy still running in Resolve is told to restart.
local SCRIPT_VERSION = 5
local POLL_SECONDS = 0.25
local STALE_SECONDS = 300
local STARTED = os.time()
math.randomseed(STARTED + math.floor((os.clock() % 1) * 1000000))
local OWNER = string.format("%d-%06d", STARTED, math.random(0, 999999))
local ARRAY = {}

local function array(list)
  return setmetatable(list or {}, ARRAY)
end

local function is_array(value)
  return getmetatable(value) == ARRAY
end

local function quote(value)
  local text = tostring(value):gsub("[%z\1-\31\\\"]", function(char)
    local escapes = {
      ["\""] = "\\\"",
      ["\\"] = "\\\\",
      ["\b"] = "\\b",
      ["\f"] = "\\f",
      ["\n"] = "\\n",
      ["\r"] = "\\r",
      ["\t"] = "\\t",
    }
    return escapes[char] or string.format("\\u%04x", string.byte(char))
  end)
  return "\"" .. text .. "\""
end

local function encode(value)
  local kind = type(value)
  if kind == "nil" then return "null" end
  if kind == "boolean" then return value and "true" or "false" end
  if kind == "number" then
    if value ~= value or value == math.huge or value == -math.huge then return "null" end
    if value == math.floor(value) and math.abs(value) < 1e15 then
      return string.format("%.0f", value)
    end
    return string.format("%.16g", value)
  end
  if kind == "string" then return quote(value) end
  if kind ~= "table" then error("Cannot encode " .. kind) end
  if is_array(value) then
    local parts = {}
    for index = 1, #value do parts[index] = encode(value[index]) end
    return "[" .. table.concat(parts, ",") .. "]"
  end
  local parts = {}
  for key, item in pairs(value) do
    if type(key) == "string" then
      parts[#parts + 1] = quote(key) .. ":" .. encode(item)
    end
  end
  return "{" .. table.concat(parts, ",") .. "}"
end

local function decode(text)
  local index = 1
  local size = #text
  local function peek()
    return text:sub(index, index)
  end
  local function skip()
    while true do
      local char = peek()
      if char == " " or char == "\t" or char == "\n" or char == "\r" then
        index = index + 1
      else
        return
      end
    end
  end
  local parse
  local function parse_string()
    index = index + 1
    local out = {}
    while index <= size do
      local char = peek()
      if char == "\"" then
        index = index + 1
        return table.concat(out)
      end
      if char == "\\" then
        index = index + 1
        local escaped = peek()
        local simple = {
          ["\""] = "\"", ["\\"] = "\\", ["/"] = "/",
          b = "\b", f = "\f", n = "\n", r = "\r", t = "\t",
        }
        if escaped == "u" then
          local hex = text:sub(index + 1, index + 4)
          index = index + 5
          local code = tonumber(hex, 16) or 0
          if code < 128 then
            out[#out + 1] = string.char(code)
          elseif code < 2048 then
            out[#out + 1] = string.char(192 + math.floor(code / 64), 128 + (code % 64))
          else
            out[#out + 1] = string.char(
              224 + math.floor(code / 4096),
              128 + math.floor((code % 4096) / 64),
              128 + (code % 64))
          end
        else
          out[#out + 1] = simple[escaped] or escaped
          index = index + 1
        end
      else
        out[#out + 1] = char
        index = index + 1
      end
    end
    error("Unterminated string")
  end
  local function parse_number()
    local start = index
    if peek() == "-" then index = index + 1 end
    while peek():match("%d") do index = index + 1 end
    if peek() == "." then
      index = index + 1
      while peek():match("%d") do index = index + 1 end
    end
    local mark = peek()
    if mark == "e" or mark == "E" then
      index = index + 1
      local sign = peek()
      if sign == "+" or sign == "-" then index = index + 1 end
      while peek():match("%d") do index = index + 1 end
    end
    return tonumber(text:sub(start, index - 1))
  end
  parse = function()
    skip()
    local char = peek()
    if char == "\"" then return parse_string() end
    if char == "-" or char:match("%d") then return parse_number() end
    if char == "t" then index = index + 4; return true end
    if char == "f" then index = index + 5; return false end
    if char == "n" then index = index + 4; return nil end
    if char == "[" then
      index = index + 1
      local list = {}
      skip()
      if peek() == "]" then index = index + 1; return list end
      while true do
        list[#list + 1] = parse()
        skip()
        local separator = peek()
        index = index + 1
        if separator == "]" then return list end
        if separator ~= "," then error("Expected , or ]") end
      end
    end
    if char == "{" then
      index = index + 1
      local object = {}
      skip()
      if peek() == "}" then index = index + 1; return object end
      while true do
        skip()
        local key = parse_string()
        skip()
        if peek() ~= ":" then error("Expected :") end
        index = index + 1
        object[key] = parse()
        skip()
        local separator = peek()
        index = index + 1
        if separator == "}" then return object end
        if separator ~= "," then error("Expected , or }") end
      end
    end
    error("Unexpected " .. char)
  end
  return parse()
end

local function call(object, method, ...)
  if object == nil then return nil end
  local args = { ... }
  local count = select("#", ...)
  local ok, value = pcall(function()
    return object[method](object, unpack(args, 1, count))
  end)
  if ok then return value end
  return nil
end

local function trim(value)
  return (tostring(value or ""):gsub("^%s+", ""):gsub("%s+$", ""))
end

local function normalize_identity(value)
  if type(value) ~= "table" then return nil end
  local project_id, timeline_id = value.project_id, value.timeline_id
  if type(project_id) ~= "string" or trim(project_id) == ""
      or type(timeline_id) ~= "string" or trim(timeline_id) == "" then
    return nil
  end
  return { project_id = project_id, timeline_id = timeline_id }
end

local function timeline_identity(timeline, project)
  return normalize_identity({
    project_id = call(project, "GetUniqueId"),
    timeline_id = call(timeline, "GetUniqueId"),
  })
end

local function require_timeline(timeline, project, expected)
  expected = normalize_identity(expected)
  if not expected then
    error("The analysis has no verified timeline identity. Read the timeline and analyze again before placing markers.")
  end
  local actual = timeline_identity(timeline, project)
  if not actual then
    error("Resolve could not identify the current project and timeline. No markers were changed.")
  end
  if actual.project_id ~= expected.project_id or actual.timeline_id ~= expected.timeline_id then
    error("The active Resolve timeline is not the analyzed timeline. Return to the analyzed timeline before placing markers. No markers were changed.")
  end
end

local function parse_fps(raw)
  if type(raw) == "number" and raw ~= 0 then return raw end
  local text = trim(raw)
  if text == "" or text == "nil" then return nil end
  local slash = text:find("/", 1, true)
  if slash then
    local numerator = tonumber(text:sub(1, slash - 1))
    local denominator = tonumber(text:sub(slash + 1))
    if numerator and denominator and denominator ~= 0 then
      return numerator / denominator
    end
  end
  return tonumber(text)
end

local function each_item(value)
  local list = {}
  if type(value) ~= "table" then return list end
  if value[1] ~= nil then
    for index = 1, #value do list[#list + 1] = value[index] end
    return list
  end
  local key, item = nil, nil
  while true do
    key, item = next(value, key)
    if key == nil then break end
    if key ~= "__flags" then list[#list + 1] = item end
  end
  return list
end

local function speed_of(item)
  local value = call(item, "GetSpeed")
  if type(value) == "table" then
    return value.speed or value.playbackSpeed or value.Speed
  end
  if type(value) == "number" or type(value) == "string" then return value end
  return nil
end

local function clip_of(item)
  local media = call(item, "GetMediaPoolItem")
  local props = media and call(media, "GetClipProperty") or {}
  if type(props) ~= "table" then props = {} end
  local path = props["File Path"] or ""
  if path == "" then return nil end
  local start_frame = math.floor(tonumber(call(item, "GetStart")) or 0)
  local end_frame = math.floor(tonumber(call(item, "GetEnd")) or 0)
  local source_start = math.floor(tonumber(call(item, "GetSourceStartFrame")) or 0)
  local source_end = math.floor(tonumber(call(item, "GetSourceEndFrame")) or 0)
  if source_end <= source_start then
    source_end = source_start + math.max(0, end_frame - start_frame)
  end
  local clip = {
    name = call(item, "GetName") or "",
    start = start_frame,
    source_start = source_start,
    source_end = source_end,
    path = path,
  }
  clip["end"] = end_frame
  local fps = parse_fps(props["FPS"])
  if fps ~= nil then clip.fps = fps end
  local speed = speed_of(item)
  if type(speed) == "number" or type(speed) == "string" then clip.speed = speed end
  return clip
end

local function is_automatic(custom)
  return tostring(custom or ""):sub(1, #AUTOMATIC) == AUTOMATIC
end

local function markers_of(timeline)
  local raw = call(timeline, "GetMarkers") or {}
  local list = {}
  for frame, info in pairs(raw) do
    if frame ~= "__flags" then
      local number = math.floor(tonumber(frame) or 0)
      if type(info) ~= "table" then info = {} end
      local custom = info.customData or info.CustomData or ""
      if custom == "" then
        custom = call(timeline, "GetMarkerCustomData", number) or ""
      end
      list[#list + 1] = {
        frame = number,
        color = tostring(info.color or ""),
        name = tostring(info.name or ""),
        note = tostring(info.note or ""),
        duration = math.floor(tonumber(info.duration) or 1),
        custom_data = tostring(custom or ""),
        automatic = is_automatic(custom),
      }
    end
  end
  table.sort(list, function(left, right) return left.frame < right.frame end)
  return array(list)
end

local function absolute_mark(value, start_frame)
  if value == nil or value == "" then return nil end
  local number = math.floor(tonumber(value) or 0)
  local start = math.floor(tonumber(start_frame) or 0)
  if start ~= 0 and number < start then return start + number end
  return number
end

local function track_names(timeline, track_type)
  local count = math.floor(tonumber(call(timeline, "GetTrackCount", track_type)) or 0)
  local names = {}
  for index = 1, count do
    names[index] = call(timeline, "GetTrackName", track_type, index) or ""
  end
  return names
end

local function clips_on(timeline, track_type, track_index)
  local found = {}
  for _, item in ipairs(each_item(call(timeline, "GetItemListInTrack", track_type, track_index))) do
    local clip = clip_of(item)
    if clip then found[#found + 1] = clip end
  end
  return array(found)
end

local function cue_warning(names)
  if #names == 0 then return "Video 1 was not found." end
  return ""
end

local function read_timeline(timeline, project)
  if timeline == nil then error("No timeline is open.") end
  local start_frame = math.floor(tonumber(call(timeline, "GetStartFrame")) or 0)
  local setting = call(timeline, "GetSetting", "timelineFrameRate")
  local fps = parse_fps(setting) or 24
  local drop_raw = trim(call(timeline, "GetSetting", "timelineDropFrameTimecode")):lower()
  -- An interlaced timeline counts fields (50 for 25i) while its timecode counts images.
  local interlace_raw = trim(call(timeline, "GetSetting", "timelineInterlaceProcessing")):lower()
  local playback_fps = parse_fps(call(timeline, "GetSetting", "timelinePlaybackFrameRate"))
  local names = track_names(timeline, "video")
  local marks = call(timeline, "GetMarkInOut") or {}
  local video_marks = type(marks) == "table" and marks.video or {}
  if type(video_marks) ~= "table" then video_marks = {} end
  local warning = cue_warning(names)
  local warnings = {}
  if warning ~= "" then warnings[#warnings + 1] = warning end
  local video = clips_on(timeline, "video", 1)
  local audio_count = math.floor(tonumber(call(timeline, "GetTrackCount", "audio")) or 0)
  local audio = audio_count >= 1 and clips_on(timeline, "audio", 1) or array({})
  if #video == 0 then warnings[#warnings + 1] = "Video 1 has no clip linked to a file." end
  if #audio == 0 then warnings[#warnings + 1] = "Audio 1 has no clip linked to a file. Lines will not be detected." end
  local project_name = call(project, "GetName")
  if type(project_name) ~= "string" then project_name = "" end
  local result = {
    project_name = project_name,
    timeline_name = call(timeline, "GetName") or "",
    timeline_identity = timeline_identity(timeline, project),
    start_frame = start_frame,
    end_frame = math.floor(tonumber(call(timeline, "GetEndFrame")) or 0),
    fps = fps,
    drop = drop_raw == "1" or drop_raw == "true",
    interlaced = interlace_raw == "1" or interlace_raw == "true",
    script_version = SCRIPT_VERSION,
    start_timecode = call(timeline, "GetStartTimecode") or "00:00:00:00",
    video_track_name = names[1] or "",
    video_clips = video,
    audio_clips = audio,
    markers = markers_of(timeline),
    warnings = array(warnings),
  }
  if playback_fps ~= nil then result.playback_fps = playback_fps end
  local mark_in = absolute_mark(video_marks["in"], start_frame)
  local mark_out = absolute_mark(video_marks["out"], start_frame)
  if mark_in ~= nil then result.mark_in = mark_in end
  if mark_out ~= nil then result.mark_out = mark_out end
  return result
end

local function in_range(frame, start_frame, end_frame)
  if start_frame == nil or end_frame == nil then return true end
  return start_frame <= frame and frame < end_frame
end

local function plan_apply(existing, proposals, start_frame, end_frame)
  local delete = {}
  local occupied = {}
  for _, marker in ipairs(existing or {}) do
    local frame = math.floor(tonumber(marker.frame) or 0)
    if in_range(frame, start_frame, end_frame) then
      if marker.automatic then delete[#delete + 1] = frame
      else occupied[frame] = true end
    end
  end
  local add, skipped = {}, {}
  for _, proposal in ipairs(proposals or {}) do
    local frame = math.floor(tonumber(proposal.frame) or 0)
    if in_range(frame, start_frame, end_frame) then
      if occupied[frame] then skipped[#skipped + 1] = frame
      else add[#add + 1] = proposal end
    end
  end
  return array(delete), array(add), array(skipped)
end

local function apply_markers(timeline, proposals, start_frame, end_frame, expected, project)
  -- Check the captured Resolve objects before even reading markers; never reacquire
  -- the active timeline between this check and the mutations below.
  require_timeline(timeline, project, expected)
  local outside, eligible = {}, 0
  for _, proposal in ipairs(proposals or {}) do
    local frame = math.floor(tonumber(proposal.frame) or 0)
    if in_range(frame, start_frame, end_frame) then
      if not MARKER_NAMES[proposal.color] then error("Unsupported marker color. No markers were changed.") end
      eligible = eligible + 1
    else
      outside[#outside + 1] = frame
    end
  end
  if eligible == 0 then
    return { verified = true, requested = #(proposals or {}), attempted = 0,
      deleted = array({}), placed = array({}), skipped = array({}), failed = array({}), outside = array(outside) }
  end
  local existing = markers_of(timeline)
  local delete, add, skipped = plan_apply(existing, proposals, start_frame, end_frame)
  table.sort(add, function(a, b) return tonumber(a.frame) < tonumber(b.frame) end)
  -- Reuse numbers when replacing a range, while preserving names on markers
  -- kept by this operation (manual markers and automatic markers outside it).
  local deleting, reserved = {}, {}
  for _, frame in ipairs(delete) do deleting[frame] = true end
  for _, marker in ipairs(existing) do
    if not deleting[marker.frame] then reserved[string.lower(marker.name or "")] = true end
  end
  local names, number = {}, 1
  for _, proposal in ipairs(add) do
    while reserved[string.format("marqueur-%03d", number)] do number = number + 1 end
    local name = string.format("marqueur-%03d", number)
    names[math.floor(tonumber(proposal.frame) or 0)] = name
    reserved[name] = true
    number = number + 1
  end
  for _, frame in ipairs(delete) do
    call(timeline, "DeleteMarkerAtFrame", frame)
  end
  local placed, failed = {}, {}
  local left = {}
  for index = 1, #skipped do left[index] = skipped[index] end
  for _, proposal in ipairs(add) do
    local frame = math.floor(tonumber(proposal.frame) or 0)
    local color = proposal.color or ""
    -- Resolve refuses an empty marker name, including on the real 25i timeline.
    -- Keep customData on every call so a failed write never becomes a manual marker.
    call(timeline, "AddMarker", frame, color, names[frame], "", 1, AUTOMATIC)
  end
  local actual = {}
  for _, marker in ipairs(markers_of(timeline)) do actual[marker.frame] = marker end
  for _, proposal in ipairs(add) do
    local frame = math.floor(tonumber(proposal.frame) or 0)
    local marker = actual[frame]
    if marker and marker.color == proposal.color and marker.name == names[frame]
        and marker.custom_data == AUTOMATIC then
      placed[#placed + 1] = frame
    else
      failed[#failed + 1] = frame
      left[#left + 1] = frame
    end
  end
  return { verified = true, requested = #(proposals or {}), attempted = #add,
    deleted = array(delete), placed = array(placed), skipped = array(left),
    failed = array(failed), outside = array(outside) }
end

local function current_timeline()
  if resolve == nil then
    error("This script must be started from Workspace > Scripts inside Resolve.")
  end
  local manager = call(resolve, "GetProjectManager")
  local project = manager and call(manager, "GetCurrentProject") or nil
  if not project then error("No project is open.") end
  local timeline = call(project, "GetCurrentTimeline")
  if not timeline then error("No timeline is open.") end
  return timeline, project
end

local function timeline_name()
  local ok, name = pcall(function()
    return current_timeline():GetName() or ""
  end)
  if ok then return name or "" end
  return ""
end

local function learning_error(text) error("Learning import: " .. text, 0) end

local function library_database(manager)
  local db = call(manager, "GetCurrentDatabase")
  if type(db) ~= "table" or not db.DbName then learning_error("the connected project library could not be identified.") end
  return { DbType = tostring(db.DbType or ""), DbName = tostring(db.DbName or ""), IpAddress = tostring(db.IpAddress or "") }
end

local function library_names(values)
  if type(values) ~= "table" then learning_error("the library names could not be read.") end
  local found = {}
  for key, name in pairs(values) do
    -- Resolve's Lua lists also carry numeric __flags bookkeeping, including
    -- lists with no names. It is metadata, as in each_item(), above.
    if key ~= "__flags" then
      if type(name) ~= "string" or name == "" or #name > 2048 then learning_error("an invalid library name was returned.") end
      found[#found + 1] = name
    end
  end
  table.sort(found)
  return found
end

local function library_goto(manager, path)
  if not call(manager, "GotoRootFolder") then learning_error("the project library root could not be opened.") end
  for _, folder in ipairs(path) do
    if not call(manager, "OpenFolder", folder) then learning_error("the project folder could not be opened: " .. folder) end
  end
end

local function learning_library()
  local manager = call(resolve, "GetProjectManager")
  local db = library_database(manager)
  local reversed, origin = {}, {}
  local at_root = false
  for _ = 1, 32 do
    local name = call(manager, "GetCurrentFolder")
    if not call(manager, "GotoParentFolder") then at_root = true; break end
    if type(name) ~= "string" then learning_error("the current project folder could not be identified.") end
    reversed[#reversed + 1] = name
  end
  if not at_root then learning_error("the project library has too many nested folders.") end
  for index = #reversed, 1, -1 do origin[#origin + 1] = reversed[index] end
  local entries, visited = {}, 0
  local function visit(path)
    visited = visited + 1
    if #path > 12 or visited > 1000 then learning_error("the project library is too large for one scan.") end
    for _, name in ipairs(library_names(call(manager, "GetProjectListInCurrentFolder"))) do
      local copied = array({})
      for _, part in ipairs(path) do copied[#copied + 1] = part end
      entries[#entries + 1] = { name = name, folder = copied, database = db }
      if #entries > 2000 then learning_error("the project library has more than 2000 projects.") end
    end
    for _, folder in ipairs(library_names(call(manager, "GetFolderListInCurrentFolder"))) do
      if not call(manager, "OpenFolder", folder) then learning_error("a project folder could not be opened.") end
      local child = {}
      for _, part in ipairs(path) do child[#child + 1] = part end
      child[#child + 1] = folder
      visit(child)
      if not call(manager, "GotoParentFolder") then learning_error("the project folder could not be restored.") end
    end
  end
  local ok, failure = pcall(function() library_goto(manager, {}); visit({}) end)
  library_goto(manager, origin)
  if not ok then error(failure, 0) end
  return { database = db, projects = array(entries) }
end

local function learning_open(command)
  local entry, expected = command.entry, command.timeline_name or ""
  if type(entry) ~= "table" or type(entry.name) ~= "string" or entry.name == ""
      or type(entry.folder) ~= "table" or #entry.folder > 12 or type(expected) ~= "string" then
    learning_error("the selected project or timeline is invalid.")
  end
  for _, part in ipairs(entry.folder) do
    if type(part) ~= "string" or part == "" then learning_error("the selected project folder is invalid.") end
  end
  local manager = call(resolve, "GetProjectManager")
  local db, wanted = library_database(manager), entry.database
  if type(wanted) ~= "table" or db.DbType ~= wanted.DbType or db.DbName ~= wanted.DbName or db.IpAddress ~= wanted.IpAddress then
    learning_error("the active project library changed. Refresh the batch list.")
  end
  library_goto(manager, entry.folder)
  local exists = false
  for _, name in ipairs(library_names(call(manager, "GetProjectListInCurrentFolder"))) do if name == entry.name then exists = true end end
  if not exists then learning_error("the selected project is no longer in its folder: " .. entry.name) end
  local opened = call(manager, "LoadProject", entry.name)
  if not opened then learning_error("Resolve did not open " .. entry.name .. ". Save any current Resolve work and retry; no project is force-closed.") end
  local current = call(manager, "GetCurrentProject")
  local project_id = call(opened, "GetUniqueId")
  if not project_id or call(current, "GetUniqueId") ~= project_id or call(opened, "GetName") ~= entry.name then
    learning_error("Resolve did not confirm the requested project as current.")
  end
  local matches, count = {}, tonumber(call(opened, "GetTimelineCount")) or 0
  for index = 1, count do
    local item = call(opened, "GetTimelineByIndex", index)
    if item and (call(item, "GetName") == expected or (expected == "" and count == 1)) then matches[#matches + 1] = item end
  end
  if #matches ~= 1 then learning_error("project " .. entry.name .. " needs exactly one matching timeline: " .. expected) end
  local selected = matches[1]
  if not call(opened, "SetCurrentTimeline", selected) then learning_error("the requested learning timeline could not be activated.") end
  local actual = call(opened, "GetCurrentTimeline")
  local identity = timeline_identity(selected, opened)
  local verified = timeline_identity(actual, current)
  if not identity or not verified or identity.project_id ~= verified.project_id or identity.timeline_id ~= verified.timeline_id then
    learning_error("Resolve did not confirm the requested timeline identity.")
  end
  return read_timeline(selected, opened)
end

local function dispatch(command, timeline, project)
  local name = command.cmd
  if name == "ping" then return { ok = true } end
  if name == "stop" then return { ok = true, stopping = true } end
  if name == "learning_library" then return learning_library() end
  if name == "learning_open" then return learning_open(command) end
  if name == "read" then return read_timeline(timeline, project) end
  if name == "seek" then
    local ok = call(timeline, "SetCurrentTimecode", command.timecode)
    return { ok = ok and true or false, timecode = command.timecode or "" }
  end
  if name == "apply" then
    error("Unchecked marker placement is no longer supported. Update VISPA MP and read the timeline again.")
  end
  if name == "apply_checked" then
    return apply_markers(timeline, command.proposals, command.start, command["end"], command.expected_timeline, project)
  end
  error("Unknown command: " .. tostring(name))
end

-- Transport. A script started from Workspace > Scripts gets no io, no ffi,
-- no require and no os.remove. It can still read a Lua file (loadfile) and save
-- Fusion's preferences to any path (SetData + SavePrefs). VISPA MP writes
-- request.lua; the script answers through the VispaMP block of link.prefs.
local DATA = "VispaMP"
local REQUEST_FILE = MAILBOX .. "\\request.lua"
local LINK_PREFS = MAILBOX .. "\\link.prefs"
local RESPONSE_SECONDS = 5
local FUSION = nil

local function hex(text)
  return (text:gsub(".", function(char) return string.format("%02x", string.byte(char)) end))
end

local function set_data(key, value)
  FUSION:SetData(key and (DATA .. "." .. key) or DATA, value)
end

local function get_data(key)
  return FUSION:GetData(DATA .. "." .. key)
end

local function publish()
  FUSION:SavePrefs(LINK_PREFS)
end

local function write_status(running, name)
  set_data("Status", hex(encode({
    running = running and true or false,
    at = os.time(),
    timeline = name or "",
    owner = OWNER,
    started = STARTED,
  })))
  publish()
end

local function read_request()
  local chunk = loadfile(REQUEST_FILE)
  if type(chunk) ~= "function" then return nil end
  local ok, text = pcall(chunk)
  if not ok or type(text) ~= "string" or text == "" then return nil end
  local decoded, request = pcall(decode, text)
  if decoded and type(request) == "table" then return request end
  return nil
end

-- VISPA MP ids are nanosecond timestamps. A request left behind by a VISPA MP
-- that gave up or crashed must not run when the script starts much later.
local function is_stale(request, now)
  local sent = tonumber(request.id)
  if not sent or sent < 1e15 then return false end
  return now - sent / 1e9 > STALE_SECONDS
end

-- The script cannot delete request.lua, so it remembers what it answered.
-- VISPA MP deletes the file once it has the answer.
local last_id = nil
local response_at = nil

local function handle_once()
  local request = read_request()
  if not request then return false end
  local id = tostring(request.id or "")
  if id == last_id then return false end
  last_id = id
  if is_stale(request, os.time()) then return false end
  local ran, result = pcall(function()
    local timeline, project = nil, nil
    if request.cmd ~= "ping" and request.cmd ~= "stop" and request.cmd ~= "learning_library" and request.cmd ~= "learning_open" then
      timeline, project = current_timeline()
    end
    return dispatch(request, timeline, project)
  end)
  local response
  if ran then response = { id = request.id, ok = true, result = result }
  else response = { id = request.id, ok = false, error = tostring(result) } end
  set_data("Response", hex(encode(response)))
  response_at = os.time()
  return true, ran and request.cmd == "stop", tostring(request.cmd or "")
end

-- Waits without a window. bmd.wait is Fusion's own pause. Spinning on
-- os.clock is the last resort.
local function pick_sleep()
  local found, wait = pcall(function() return bmd and bmd.wait end)
  if found and type(wait) == "function" then
    return function(seconds) bmd.wait(seconds) end, "bmd.wait"
  end
  return function(seconds)
    local stop = os.clock() + seconds
    while os.clock() < stop do end
  end, "busy"
end

local function self_check()
  local value = decode('{"id":"abc","cmd":"apply","start":null,"end":10,"proposals":[{"frame":3,"color":"Green"}]}')
  assert(value.id == "abc")
  assert(value.start == nil)
  assert(value["end"] == 10)
  assert(value.proposals[1].frame == 3)
  local again = decode(encode({ id = "abc", ok = true, result = { ok = true } }))
  assert(again.id == "abc" and again.ok == true and again.result.ok == true)
  assert(encode(array({ 1, 2 })) == "[1,2]")
  assert(absolute_mark(100, 86400) == 86500)
  assert(absolute_mark(86500, 86400) == 86500)
  assert(cue_warning({ "CUE_SOURCE" }) == "")
  assert(cue_warning({ "Animation" }) == "")
  assert(cue_warning({ "Animation", "CUE_SOURCE" }) == "")
  assert(cue_warning({}) == "Video 1 was not found.")
  local delete, add, skipped = plan_apply(
    { { frame = 1, automatic = false }, { frame = 2, automatic = true } },
    { { frame = 1, color = "Blue" }, { frame = 3, color = "Cyan" } },
    0, 10)
  assert(delete[1] == 2 and add[1].frame == 3 and skipped[1] == 1)
  local reads, mutations, test_markers = 0, 0, {}
  local timeline = {
    GetUniqueId = function() return "timeline-a" end,
    GetMarkers = function() reads = reads + 1; return test_markers end,
    DeleteMarkerAtFrame = function() mutations = mutations + 1 end,
    AddMarker = function(_, frame, color, name, note, duration, custom)
      mutations = mutations + 1
      if not name or name == "" then return false end
      test_markers[frame] = { color = color, name = name, note = note, duration = duration, customData = custom }
      return true
    end,
  }
  local project = { GetUniqueId = function() return "project-a" end }
  local function rejected(command)
    assert(not pcall(dispatch, command, timeline, project))
    assert(reads == 0 and mutations == 0)
  end
  rejected({ cmd = "apply", proposals = { { frame = 3, color = "Green" } } })
  rejected({ cmd = "apply_checked", expected_timeline = { project_id = "project-a", timeline_id = "timeline-b" } })
  rejected({ cmd = "apply_checked", expected_timeline = { project_id = "project-b", timeline_id = "timeline-a" } })
  rejected({ cmd = "apply_checked" })
  rejected({ cmd = "apply_checked", expected_timeline = { project_id = "project-a", timeline_id = " " } })
  rejected({ cmd = "apply_checked", expected_timeline = { project_id = "project-a", timeline_id = 1 } })
  local placed = dispatch({ cmd = "apply_checked", expected_timeline = { project_id = "project-a", timeline_id = "timeline-a" },
    proposals = { { frame = 3, color = "Green" } } }, timeline, project)
  assert(placed.placed[1] == 3 and mutations == 1)
  assert(dispatch({ cmd = "stop" }, nil).stopping == true)
  assert(is_stale({ id = "1700000000000000000" }, 1700000000 + 301) == true)
  assert(is_stale({ id = "1700000000000000000" }, 1700000000 + 10) == false)
  assert(is_stale({ id = "abc" }, 1700000000) == false)
  assert(hex("A{\n") == "417b0a")
  local sleep, how = pick_sleep()
  sleep(0.01)
  print("vispa-mp sleep: " .. how)
  print("vispa-mp self-check ok")
end

local function serve()
  -- No window: a script window is a Studio feature and the free edition stops on it.
  local sleep, how = pick_sleep()
  local ok, err = pcall(function()
    set_data("Owner", OWNER)
    write_status(true, timeline_name())
  end)
  if not ok then
    print("VISPA MP: " .. tostring(err))
    return
  end
  print("VISPA MP: listening. Keep working in Resolve; VISPA MP can read the timeline and place markers until Resolve closes.")
  if how == "busy" then
    print("VISPA MP: no sleep function was found, so this script keeps one CPU core busy.")
  end
  local beat = os.time()
  local reason = nil
  while reason == nil do
    -- Running the script again starts a new copy; the newest one owns the link.
    local owner_ok, owner = pcall(get_data, "Owner")
    if owner_ok and owner ~= OWNER then
      reason = "a newer VISPA_MP took over"
    else
      local handled, stopping, command = false, false, ""
      local ran, problem = pcall(function()
        handled, stopping, command = handle_once()
      end)
      if not ran then print("VISPA MP: " .. tostring(problem)) end
      if stopping then
        reason = "VISPA MP asked it to stop"
        pcall(write_status, false, "")
        -- Leave nothing behind in Resolve's own preferences.
        pcall(set_data, nil, nil)
      else
        local now = os.time()
        if response_at and not handled and now - response_at > RESPONSE_SECONDS then
          pcall(set_data, "Response", nil)
          response_at = nil
        end
        if handled or now ~= beat then
          pcall(write_status, true, timeline_name())
          beat = now
        end
        if handled and command ~= "ping" then
          print("VISPA MP: answered " .. command .. ".")
        end
        sleep(POLL_SECONDS)
      end
    end
  end
  print("VISPA MP: stopped (" .. reason .. ").")
end

-- The Console defines `resolve`. Workspace > Scripts often gives only `app`
-- (Fusion), which hands out Resolve through GetResolve.
local function find_resolve()
  if resolve then return resolve end
  for _, host in ipairs({ app or false, fusion or false, fu or false }) do
    if host then
      local value = call(host, "GetResolve")
      if value then return value end
    end
  end
  return nil
end

local host = find_resolve()
if not host then
  self_check()
  return
end
resolve = host
FUSION = fusion or app or fu or call(host, "Fusion")
if not FUSION then
  print("VISPA MP: Fusion is not reachable from this script, so it cannot talk to VISPA MP.")
  return
end
serve()
