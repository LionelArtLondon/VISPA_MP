-- VISPA MP bridge for the free edition of DaVinci Resolve.
-- Workspace > Scripts lists Lua only on this machine, so this file is the menu entry.
-- Run it once per Resolve session. It opens no window (a script window is a
-- Studio feature) and keeps answering VISPA MP through cache/resolve_link until
-- Resolve closes, VISPA MP sends "stop", or the script is run again.

local MAILBOX = [[__MAILBOX__]]
local AUTOMATIC = "vispa-mp"
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
  local cue = {}
  for index, name in ipairs(names) do
    if trim(name):lower() == "cue_source" then cue[#cue + 1] = tostring(index) end
  end
  if #cue == 0 then
    return "No track is named CUE_SOURCE. Analysis uses video 1. The Cue exporter looks for a track with that name."
  end
  if not (#cue == 1 and cue[1] == "1") then
    return "CUE_SOURCE is not video 1 (track " .. table.concat(cue, ", ") .. "). Analysis stays on video 1."
  end
  return ""
end

local function read_timeline(timeline)
  if timeline == nil then error("No timeline is open.") end
  local start_frame = math.floor(tonumber(call(timeline, "GetStartFrame")) or 0)
  local setting = call(timeline, "GetSetting", "timelineFrameRate")
  local fps = parse_fps(setting) or 24
  local drop_raw = trim(call(timeline, "GetSetting", "timelineDropFrameTimecode")):lower()
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
  local result = {
    timeline_name = call(timeline, "GetName") or "",
    start_frame = start_frame,
    end_frame = math.floor(tonumber(call(timeline, "GetEndFrame")) or 0),
    fps = fps,
    drop = drop_raw == "1" or drop_raw == "true",
    start_timecode = call(timeline, "GetStartTimecode") or "00:00:00:00",
    video_track_name = names[1] or "",
    video_clips = video,
    audio_clips = audio,
    markers = markers_of(timeline),
    warnings = array(warnings),
  }
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

local function apply_markers(timeline, proposals, start_frame, end_frame)
  local delete, add, skipped = plan_apply(markers_of(timeline), proposals, start_frame, end_frame)
  for _, frame in ipairs(delete) do
    call(timeline, "DeleteMarkerAtFrame", frame)
  end
  local placed = {}
  local left = {}
  for index = 1, #skipped do left[index] = skipped[index] end
  for _, proposal in ipairs(add) do
    local frame = math.floor(tonumber(proposal.frame) or 0)
    local color = proposal.color or ""
    local ok = call(timeline, "AddMarker", frame, color, "", "", 1, AUTOMATIC)
    if not ok then ok = call(timeline, "AddMarker", frame, color, "", "", 1) end
    if ok then placed[#placed + 1] = frame
    else left[#left + 1] = frame end
  end
  return { deleted = array(delete), placed = array(placed), skipped = array(left) }
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
  return timeline
end

local function timeline_name()
  local ok, name = pcall(function()
    return current_timeline():GetName() or ""
  end)
  if ok then return name or "" end
  return ""
end

local function dispatch(command, timeline)
  local name = command.cmd
  if name == "ping" then return { ok = true } end
  if name == "stop" then return { ok = true, stopping = true } end
  if name == "read" then return read_timeline(timeline) end
  if name == "seek" then
    local ok = call(timeline, "SetCurrentTimecode", command.timecode)
    return { ok = ok and true or false, timecode = command.timecode or "" }
  end
  if name == "apply" then
    return apply_markers(timeline, command.proposals, command.start, command["end"])
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
    local timeline = nil
    if request.cmd ~= "ping" and request.cmd ~= "stop" then timeline = current_timeline() end
    return dispatch(request, timeline)
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
  assert(cue_warning({}) == "Video 1 was not found.")
  local delete, add, skipped = plan_apply(
    { { frame = 1, automatic = false }, { frame = 2, automatic = true } },
    { { frame = 1, color = "Blue" }, { frame = 3, color = "Cyan" } },
    0, 10)
  assert(delete[1] == 2 and add[1].frame == 3 and skipped[1] == 1)
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
