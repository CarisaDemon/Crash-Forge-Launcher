
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

[System.Windows.Forms.Application]::EnableVisualStyles()
$ErrorActionPreference = "Stop"

$script:RootPath = ""

# Display names only. Files are always saved as level_XX.ogg.
$script:KnownNames = @{
    0  = "DINGO_CANYON"
    1  = "DRAGON_MINES"
    2  = "BLIZZARD_BLUFF"
    3  = "CRASH_COVE"
    4  = "TIGER_TEMPLE"
    5  = "PAPU_PYRAMID"
    6  = "ROO_TUBES"
    7  = "HOT_AIR_SKYWAY"
    8  = "SEWER_SPEEDWAY"
    9  = "MYSTERY_CAVES"
    10 = "CORTEX_CASTLE"
    11 = "N_GIN_LABS"
    12 = "POLAR_PASS"
    13 = "OXIDE_STATION"
    14 = "COCO_PARK"
    15 = "TINY_ARENA"
    16 = "SLIDE_COLISEUM"
    17 = "TURBO_TRACK"
    18 = "NITRO_COURT"
    19 = "RAMPAGE_RUINS"
    20 = "PARKING_LOT"
    21 = "SKULL_ROCK"
    22 = "THE_NORTH_BOWL"
    23 = "ROCKY_ROAD"
    24 = "LAB_BASEMENT"
    25 = "GEM_STONE_VALLEY"
    26 = "N_SANITY_BEACH"
    27 = "THE_LOST_RUINS"
    28 = "GLACIER_PARK"
    29 = "CITADEL_CITY"
    30 = "INTRO_RACE_TODAY"
    31 = "INTRO_COCO"
    32 = "INTRO_TINY"
    33 = "INTRO_POLAR"
    34 = "INTRO_DINGODILE"
    35 = "INTRO_CORTEX"
    36 = "INTRO_SPACE"
    37 = "INTRO_CRASH"
    38 = "INTRO_OXIDE"
    39 = "MAIN_MENU_LEVEL"
    40 = "ADVENTURE_CHARACTER_SELECT"
    41 = "NAUGHTY_DOG_CRATE"
    42 = "OXIDE_ENDING"
    43 = "OXIDE_TRUE_ENDING"
    44 = "CREDITS_LEVEL"
    45 = "CREDITS_CRASH"
    46 = "CREDITS_TINY"
    47 = "CREDITS_COCO"
    48 = "CREDITS_N_GIN"
    49 = "CREDITS_DINGO"
    50 = "CREDITS_POLAR"
    51 = "CREDITS_PURA"
    52 = "CREDITS_PINSTRIPE"
    53 = "CREDITS_PAPU"
    54 = "CREDITS_ROO"
    55 = "CREDITS_JOE"
    56 = "CREDITS_TROPY"
    57 = "CREDITS_PENTA"
    58 = "CREDITS_FAKE_CRASH"
    59 = "CREDITS_OXIDE"
    60 = "CREDITS_AMI"
    61 = "CREDITS_ISABELLA"
    62 = "CREDITS_LIZ"
    63 = "CREDITS_MEGUMI"
    64 = "SCRAPBOOK"
    99 = "HANGOUT_HUB"
}

# Show base references even without an OGG.
# Reference IDs are assigned in the exact order supplied by the user (0..64).
$script:ReferenceIds = @(0..64) + @(99)

# ---------- Colors ----------
$C_BG      = [System.Drawing.Color]::FromArgb(8,9,11)
$C_PANEL   = [System.Drawing.Color]::FromArgb(15,18,22)
$C_PANEL2  = [System.Drawing.Color]::FromArgb(21,24,29)
$C_TEXT    = [System.Drawing.Color]::FromArgb(242,242,239)
$C_MUTED   = [System.Drawing.Color]::FromArgb(143,149,157)
$C_ACCENT  = [System.Drawing.Color]::FromArgb(255,106,0)
$C_DANGER  = [System.Drawing.Color]::FromArgb(125,36,27)
$C_BORDER  = [System.Drawing.Color]::FromArgb(56,63,71)
$C_HOVER   = [System.Drawing.Color]::FromArgb(76,31,8)
$C_INPUT   = [System.Drawing.Color]::FromArgb(20,24,29)
$C_SUCCESS = [System.Drawing.Color]::FromArgb(86,196,122)

function Show-Error([string]$msg) {
    [System.Windows.Forms.MessageBox]::Show(
        $msg, "Crash Forge OGG Toolkit",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
}

function Show-Info([string]$msg) {
    [System.Windows.Forms.MessageBox]::Show(
        $msg, "Crash Forge OGG Toolkit",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information
    ) | Out-Null
}

function MusicDirs {
    if ([string]::IsNullOrWhiteSpace($script:RootPath)) { return @() }
    return @(
        (Join-Path $script:RootPath "assets\MUSIC_CUSTOM")
    )
}

function Test-CtrRoot([string]$path) {
    if (!(Test-Path $path -PathType Container)) { return $false }
    return (Test-Path -LiteralPath (Join-Path $path "ctr_native.exe") -PathType Leaf) -or
           (Test-Path -LiteralPath (Join-Path $path "ctr-native.exe") -PathType Leaf)
}

function Ensure-MusicDirs {
    foreach ($d in (MusicDirs)) {
        if (!(Test-Path $d)) {
            [IO.Directory]::CreateDirectory($d) | Out-Null
        }
    }
}

function Set-Root([string]$path) {
    if ([string]::IsNullOrWhiteSpace($path)) { return $false }

    try {
        $path = [Environment]::ExpandEnvironmentVariables($path.Trim().Trim('"'))
        if ($path -match '(?i)\\ctr[-_]native\.exe$') {
            $path = Split-Path $path -Parent
        }
        $resolved = (Resolve-Path -LiteralPath $path).Path
    }
    catch {
        Show-Error "Folder not found:`n$path"
        return $false
    }

    if (!(Test-CtrRoot $resolved)) {
        Show-Error "Select the compiled game folder containing ctr_native.exe:`n$resolved"
        return $false
    }

    try { [IO.Directory]::CreateDirectory((Join-Path $resolved "assets\MUSIC_CUSTOM")) | Out-Null }
    catch {
        Show-Error ("Could not create the music folder.`n`n" + $_.Exception.Message)
        return $false
    }

    $script:RootPath = $resolved
    $pathBox.Text = $resolved
    Refresh-List
    return $true
}

function Apply-RootFromBox {
    $entered = $pathBox.Text.Trim()
    if ([string]::IsNullOrWhiteSpace($entered)) {
        Show-Error "Enter the game folder path or click Browse."
        return $false
    }
    if ($entered -eq $script:RootPath) { return $true }
    return (Set-Root $entered)
}

function Pick-Root {
    $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
    $dlg.Description = "Select the folder containing ctr_native.exe"
    if ($script:RootPath) { $dlg.SelectedPath = $script:RootPath }

    if ($dlg.ShowDialog($form) -eq [System.Windows.Forms.DialogResult]::OK) {
        [void](Set-Root $dlg.SelectedPath)
    }
}

function Get-DisplayName([int]$id) {
    if ($script:KnownNames.ContainsKey($id)) {
        return $script:KnownNames[$id]
    }
    return "Level $id"
}

function Get-CustomTrackFolders {
    # Scan new <game>/mods/<web-id> and legacy assets/mods/tracks/<id>.
    if (!$script:RootPath) { return @() }
    $mods = Join-Path $script:RootPath "mods"
    $roots = @($mods, (Join-Path $script:RootPath "assets\mods\tracks"))
    $found = @{}
    foreach ($base in $roots) {
        if (!(Test-Path -LiteralPath $base -PathType Container)) { continue }
        foreach ($folder in (Get-ChildItem -LiteralPath $base -Directory -ErrorAction SilentlyContinue)) {
            if (($folder.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { continue }
            if ($folder.Name -notmatch '^[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}$') { continue }
            $ini = Join-Path $folder.FullName "track.ini"
            if (!(Test-Path -LiteralPath $ini -PathType Leaf)) { continue }
            if ((Get-Item -LiteralPath $ini).Length -gt 32768) { continue }
            $track = @{}
            $meta = @{}
            $section = ""
            foreach ($raw in (Get-Content -LiteralPath $ini -ErrorAction SilentlyContinue)) {
                $line = ([string]$raw).Trim().TrimStart([char]0xFEFF)
                if ($line -match '^\[([^]]+)\]$') {
                    $section = $Matches[1].ToLowerInvariant()
                } elseif ($line -match '^([a-zA-Z_]+)\s*=\s*(.*?)\s*$') {
                    if ($section -eq "track") { $track[$Matches[1].ToLowerInvariant()] = $Matches[2] }
                    if ($section -eq "forge_mod") { $meta[$Matches[1].ToLowerInvariant()] = $Matches[2] }
                }
            }
            if ($track["enabled"] -notmatch '^(?i:true|1|yes)$') { continue }
            if ($track["format"] -ine "native_lev_vrm") { continue }
            if ($meta.Count -gt 0 -and
                ($meta["id"] -notmatch "^[a-z0-9][a-z0-9_-]{0,63}$" -or
                 $meta["type"] -ine "Track")) { continue }
            $lev = if ($track["lev"]) { $track["lev"] } else { "data.lev" }
            $vrm = if ($track["vrm"]) { $track["vrm"] } else { "data.vrm" }
            if ($lev -notmatch '^[a-zA-Z0-9_.-]+\.lev$' -or
                $vrm -notmatch '^[a-zA-Z0-9_.-]+\.vrm$') { continue }
            if (!(Test-Path -LiteralPath (Join-Path $folder.FullName $lev) -PathType Leaf) -or
                !(Test-Path -LiteralPath (Join-Path $folder.FullName $vrm) -PathType Leaf)) { continue }
            if (!$found.ContainsKey($folder.Name.ToLowerInvariant())) {
                $name = if ($track["name"]) { $track["name"].Trim() } else { $folder.Name }
                $found[$folder.Name.ToLowerInvariant()] = [PSCustomObject]@{
                    Slug = $folder.Name
                    Name = $name
                    Directory = $folder.FullName
                }
            }
        }
    }
    return @($found.Values | Sort-Object Name,Slug)
}

function Get-TrackRows {
    $rows = @{}

    # 1) Always create base references.
    foreach ($id in $script:ReferenceIds) {
        $fileName = "level_{0:D2}.ogg" -f $id
        $rows[$fileName.ToLowerInvariant()] = [PSCustomObject]@{
            ID = $id
            Name = Get-DisplayName $id
            File = $fileName
            Paths = New-Object System.Collections.ArrayList
            HasFinal = $false
            IsReference = $true
        }
    }

    # 2) Detect installed OGG files.
    foreach ($d in (MusicDirs)) {
        if (!(Test-Path $d)) { continue }

        Get-ChildItem $d -Filter *.ogg -File -ErrorAction SilentlyContinue | ForEach-Object {
            $name = $_.Name
            $key = $name.ToLowerInvariant()

            if ($name -match '^level_(\d+)\.ogg$') {
                $id = [int]$matches[1]

                if (!$rows.ContainsKey($key)) {
                    # Add extra/custom IDs automatically.
                    $rows[$key] = [PSCustomObject]@{
                        ID = $id
                        Name = Get-DisplayName $id
                        File = $name
                        Paths = New-Object System.Collections.ArrayList
                        HasFinal = $false
                        IsReference = $false
                    }
                }

                [void]$rows[$key].Paths.Add($_.FullName)
            }
            elseif ($name -match '^level_(\d+)_final\.ogg$') {
                $id = [int]$matches[1]
                $normalName = "level_{0:D2}.ogg" -f $id
                $normalKey = $normalName.ToLowerInvariant()
                if (!$rows.ContainsKey($normalKey)) {
                    $rows[$normalKey] = [PSCustomObject]@{
                        ID = $id
                        Name = Get-DisplayName $id
                        File = $normalName
                        Paths = New-Object System.Collections.ArrayList
                        HasFinal = $false
                        IsReference = $false
                    }
                }
                $rows[$normalKey].HasFinal = $true
            }
            else {
                # Legacy/nonstandard file.
                if (!$rows.ContainsKey($key)) {
                    $rows[$key] = [PSCustomObject]@{
                        ID = ""
                        Name = "[Legacy] " + [IO.Path]::GetFileNameWithoutExtension($name)
                        File = $name
                        Paths = New-Object System.Collections.ArrayList
                        HasFinal = $false
                        IsReference = $false
                    }
                }

                [void]$rows[$key].Paths.Add($_.FullName)
            }
        }
    }

    # Audio stays in each custom module, never in the Crash Cove level_03 slot.
    foreach ($mod in (Get-CustomTrackFolders)) {
        $file = "music.ogg"
        if (!(Test-Path -LiteralPath (Join-Path $mod.Directory $file) -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $mod.Directory "track.ogg") -PathType Leaf)) {
            $file = "track.ogg"
        }
        $row = [PSCustomObject]@{
            ID = ""
            Name = "[CUSTOM] " + $mod.Name
            File = $file
            Paths = New-Object System.Collections.ArrayList
            HasFinal = (Test-Path -LiteralPath (Join-Path $mod.Directory "music_final.ogg") -PathType Leaf) -or
                       (Test-Path -LiteralPath (Join-Path $mod.Directory "track_final.ogg") -PathType Leaf)
            IsReference = $true
            IsCustom = $true
            ModFolder = $mod.Directory
            Slug = $mod.Slug
        }
        $full = Join-Path $mod.Directory $file
        if (Test-Path -LiteralPath $full -PathType Leaf) {
            [void]$row.Paths.Add($full)
        }
        $rows["custom:" + $mod.Slug.ToLowerInvariant()] = $row
    }

    return $rows.Values | Sort-Object `
        @{Expression={ if ($null -eq $_.ID -or [string]::IsNullOrWhiteSpace([string]$_.ID)) { 999999 } else { [int]$_.ID }}}, `
        File
}

function Refresh-List {
    $list.BeginUpdate()
    try {
        $list.Items.Clear()

        if ([string]::IsNullOrWhiteSpace($script:RootPath)) {
            $status.Text = "Select or enter the folder containing ctr_native.exe to begin."
            return
        }

        foreach ($r in (Get-TrackRows)) {
            $copies = $r.Paths.Count

            if ($copies -gt 0) {
                $copyText = if ($r.HasFinal) { "OGG + Final" } else { "OGG" }
            } elseif ($r.HasFinal) {
                $copyText = "Final only"
            } else {
                $copyText = "—"
            }

            $displayId = if ($r.IsCustom) { "MOD" } else { [string]$r.ID }
            $item = New-Object System.Windows.Forms.ListViewItem($displayId)
            [void]$item.SubItems.Add($r.Name)
            [void]$item.SubItems.Add($r.File)
            [void]$item.SubItems.Add($copyText)

            if (($copies -eq 0) -and !$r.HasFinal) {
                $item.ForeColor = $C_MUTED
            }
            else {
                $item.ForeColor = $C_TEXT
            }

            $item.Tag = $r
            [void]$list.Items.Add($item)
        }

        $installed = @((Get-TrackRows) | Where-Object { $_.Paths.Count -gt 0 }).Count
        $status.Text = "{0} track(s) with custom OGG files. All reference IDs are shown." -f $installed
    }
    finally {
        $list.EndUpdate()
    }
}

function Prompt-TrackId {
    $f = New-Object System.Windows.Forms.Form
    $f.Text = "Assign Level ID"
    $f.StartPosition = "CenterParent"
    $f.ClientSize = New-Object System.Drawing.Size(380,150)
    $f.FormBorderStyle = "FixedDialog"
    $f.MaximizeBox = $false
    $f.MinimizeBox = $false
    $f.BackColor = $C_BG
    $f.ForeColor = $C_TEXT

    $lab = New-Object System.Windows.Forms.Label
    $lab.Text = "Level ID (example: 3, 26, 42)"
    $lab.AutoSize = $true
    $lab.ForeColor = $C_TEXT
    $lab.Location = New-Object System.Drawing.Point(18,18)

    $txt = New-Object System.Windows.Forms.NumericUpDown
    $txt.Minimum = 0
    $txt.Maximum = 999
    $txt.Value = 3
    $txt.Location = New-Object System.Drawing.Point(20,48)
    $txt.Width = 330
    $txt.Font = New-Object System.Drawing.Font("Segoe UI",10)

    $ok = New-Object System.Windows.Forms.Button
    $ok.Text = "OK"
    $ok.Location = New-Object System.Drawing.Point(190,94)
    $ok.Size = New-Object System.Drawing.Size(75,32)
    $ok.FlatStyle = "Flat"
    $ok.BackColor = $C_ACCENT
    $ok.ForeColor = [System.Drawing.Color]::White

    $cancel = New-Object System.Windows.Forms.Button
    $cancel.Text = "Cancel"
    $cancel.Location = New-Object System.Drawing.Point(275,94)
    $cancel.Size = New-Object System.Drawing.Size(75,32)
    $cancel.FlatStyle = "Flat"
    $cancel.BackColor = $C_PANEL2
    $cancel.ForeColor = $C_TEXT

    $ok.Add_Click({
        $script:PromptResult = [int]$txt.Value
        $f.DialogResult = [System.Windows.Forms.DialogResult]::OK
        $f.Close()
    })
    $cancel.Add_Click({
        $f.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
        $f.Close()
    })

    $f.Controls.AddRange(@($lab,$txt,$ok,$cancel))
    $f.AcceptButton = $ok
    $f.CancelButton = $cancel

    $script:PromptResult = $null
    if ($f.ShowDialog($form) -eq [System.Windows.Forms.DialogResult]::OK) {
        return $script:PromptResult
    }
    return $null
}

function Test-OggVorbis([IO.Stream]$stream) {
    $stream.Position = 0
    $reader = [IO.BinaryReader]::new($stream, [Text.Encoding]::ASCII, $true)
    try {
        $page = $reader.ReadBytes(27)
        if ($page.Length -ne 27) { return $false }
        if ([Text.Encoding]::ASCII.GetString($page, 0, 4) -ne "OggS") { return $false }
        if ($page[4] -ne 0) { return $false }
        $segments = $reader.ReadBytes([int]$page[26])
        if ($segments.Length -ne [int]$page[26]) { return $false }
        $packet = $reader.ReadBytes(7)
        return (($packet.Length -eq 7) -and ($packet[0] -eq 1) -and
            ([Text.Encoding]::ASCII.GetString($packet, 1, 6) -eq "vorbis"))
    }
    finally {
        $reader.Dispose()
        $stream.Position = 0
    }
}

function Copy-And-Verify([string]$source, [string]$dest) {
    $sourceStream = $null
    $temp = $null
    try {
        $sourceFull = [IO.Path]::GetFullPath($source)
        $destFull = [IO.Path]::GetFullPath($dest)
        $parent = Split-Path $destFull -Parent
        [IO.Directory]::CreateDirectory($parent) | Out-Null

        $sourceStream = [IO.File]::Open($sourceFull, [IO.FileMode]::Open,
            [IO.FileAccess]::Read, [IO.FileShare]::Read)
        $bytes = $sourceStream.Length
        if ($bytes -le 0) { throw "The source file is empty." }
        if (!(Test-OggVorbis $sourceStream)) {
            throw "The file must be OGG Vorbis (not Opus or a file renamed to .ogg)."
        }

        if (![string]::Equals($sourceFull, $destFull,
            [StringComparison]::OrdinalIgnoreCase)) {
            $temp = Join-Path $parent ("." + [IO.Path]::GetFileName($destFull) +
                "." + [Guid]::NewGuid().ToString("N") + ".tmp")
            $destStream = [IO.File]::Open($temp, [IO.FileMode]::CreateNew,
                [IO.FileAccess]::Write, [IO.FileShare]::None)
            try {
                $sourceStream.CopyTo($destStream)
                $destStream.Flush($true)
                if ($destStream.Length -ne $bytes) {
                    throw "The OGG file could not be fully copied."
                }
            }
            finally { $destStream.Dispose() }

            $sourceStream.Dispose()
            $sourceStream = $null
            [IO.File]::Copy($temp, $destFull, $true)
        }

        $check = [IO.File]::OpenRead($destFull)
        try {
            if ($check.Length -ne $bytes) {
                throw "The copied file has an unexpected size."
            }
        }
        finally { $check.Dispose() }

        return [PSCustomObject]@{
            Success = $true
            Path = $destFull
            Error = ""
            Bytes = $bytes
        }
    }
    catch {
        return [PSCustomObject]@{
            Success = $false
            Path = $dest
            Error = $_.Exception.Message
            Bytes = 0
        }
    }
    finally {
        if ($sourceStream) { $sourceStream.Dispose() }
        if ($temp -and (Test-Path -LiteralPath $temp)) {
            Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
        }
    }
}

function Set-CustomTrackAudio([string]$folder,[string]$format,[string]$filename) {
    $ini = Join-Path $folder "track.ini"
    $lines = @(Get-Content -LiteralPath $ini -Encoding UTF8)
    $output = New-Object System.Collections.ArrayList
    $inside = $false
    $done = $false
    $values = @("enabled = true", "source = $format", "file = $filename", "custom_samples = 0")
    foreach ($line in $lines) {
        if ($line -match '^\s*\[([^]]+)\]\s*$') {
            if ($inside -and !$done) {
                foreach ($value in $values) { [void]$output.Add($value) }
                $done = $true
            }
            $inside = ($Matches[1] -ieq "music")
        } elseif ($inside -and $line -match '^\s*(enabled|source|file|custom_samples)\s*=') {
            continue
        }
        [void]$output.Add($line)
    }
    if (!$done) {
        if (!$inside) { [void]$output.Add(""); [void]$output.Add("[music]") }
        foreach ($value in $values) { [void]$output.Add($value) }
    }
    $temp = Join-Path $folder ("track.ini." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $newText = ($output -join [Environment]::NewLine) + [Environment]::NewLine
        [IO.File]::WriteAllText($temp,$newText,[Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temp -Destination $ini -Force
    } finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    }
}

function Add-MusicForCustom($modRow) {
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = "Select OGG for " + $modRow.Name
    $dialog.Filter = "OGG Vorbis (*.ogg)|*.ogg"
    $dialog.CheckFileExists = $true
    if ($dialog.ShowDialog($form) -ne [System.Windows.Forms.DialogResult]::OK) { return }
    try {
        $destination = Join-Path $modRow.ModFolder "music.ogg"
        $result = Copy-And-Verify $dialog.FileName $destination
        if (!$result.Success) { throw $result.Error }
        Set-CustomTrackAudio $modRow.ModFolder "ogg" "music.ogg"
        Refresh-List
        $status.Text = "Custom mod OGG installed: $($modRow.Slug)"
        Show-Info ("Music saved inside mod: " + $destination)
    } catch {
        Show-Error ("Could not save custom track music: " + $_.Exception.Message)
    }
}

function Add-Music {
    if ($list.SelectedItems.Count -gt 0 -and $list.SelectedItems[0].Tag.IsCustom) {
        Add-MusicForCustom $list.SelectedItems[0].Tag
        return
    }
    if ($pathBox.Text.Trim() -and $pathBox.Text.Trim() -ne $script:RootPath -and !(Apply-RootFromBox)) { return }
    if ([string]::IsNullOrWhiteSpace($script:RootPath)) {
        Pick-Root
        if ([string]::IsNullOrWhiteSpace($script:RootPath)) { return }
    }

    $dlg = New-Object System.Windows.Forms.OpenFileDialog
    $dlg.Title = "Select an OGG track"
    $dlg.Filter = "OGG Vorbis (*.ogg)|*.ogg"
    $dlg.CheckFileExists = $true

    if ($dlg.ShowDialog($form) -ne [System.Windows.Forms.DialogResult]::OK) { return }

    $id = Prompt-TrackId
    if ($null -eq $id) { return }

    $destName = "level_{0:D2}.ogg" -f $id
    $results = New-Object System.Collections.ArrayList

    Ensure-MusicDirs

    foreach ($d in (MusicDirs)) {
        $dest = Join-Path $d $destName
        [void]$results.Add((Copy-And-Verify $dlg.FileName $dest))
    }

    Refresh-List

    $okCount = @($results | Where-Object { $_.Success }).Count
    if ($okCount -eq 1) {
        $bytes = ($results | Select-Object -First 1).Bytes
        $status.Text = "OK: $destName - $bytes bytes."
        Show-Info ("Track imported successfully.`n`n" +
            "Level ID: $id`n" +
            "File: $destName`n" +
            "Size: $bytes bytes.")
    }
    else {
        Refresh-List

        $errors = ($results | Where-Object { !$_.Success } | ForEach-Object {
            "$($_.Path)`n  $($_.Error)"
        }) -join "`n`n"

        Show-Error ("Import failed.`n`n" +
            "Successful files: $okCount/1`n`n" +
            $errors)
    }
}

function Add-MusicForId([int]$id) {
    if ($pathBox.Text.Trim() -and $pathBox.Text.Trim() -ne $script:RootPath -and !(Apply-RootFromBox)) { return }
    if ([string]::IsNullOrWhiteSpace($script:RootPath)) {
        Pick-Root
        if ([string]::IsNullOrWhiteSpace($script:RootPath)) { return }
    }

    $dlg = New-Object System.Windows.Forms.OpenFileDialog
    $dlg.Title = "Select an OGG track"
    $dlg.Filter = "OGG Vorbis (*.ogg)|*.ogg"
    $dlg.CheckFileExists = $true

    if ($dlg.ShowDialog($form) -ne [System.Windows.Forms.DialogResult]::OK) { return }

    $destName = "level_{0:D2}.ogg" -f $id
    $results = New-Object System.Collections.ArrayList

    Ensure-MusicDirs

    foreach ($d in (MusicDirs)) {
        $dest = Join-Path $d $destName
        [void]$results.Add((Copy-And-Verify $dlg.FileName $dest))
    }

    Refresh-List

    $okCount = @($results | Where-Object { $_.Success }).Count
    if ($okCount -eq 1) {
        Show-Info ("Track imported successfully.`n`n" +
            "Level ID: $id`n" +
            "File: $destName.")
    }
    else {
        $errors = ($results | Where-Object { !$_.Success } | ForEach-Object {
            "$($_.Path)`n  $($_.Error)"
        }) -join "`n`n"

        Show-Error ("Import failed.`n`n" +
            "Verified files: $okCount/1`n`n" +
            $errors)
    }
}

function Find-FFmpeg {
    $localCandidates = @(
        (Join-Path $PSScriptRoot "tools\ffmpeg.exe"),
        (Join-Path $PSScriptRoot "ffmpeg.exe")
    )

    foreach ($p in $localCandidates) {
        if (Test-Path $p -PathType Leaf) { return $p }
    }

    $cmd = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    return $null
}

function Install-FFmpegForToolkit {
    $answer = [System.Windows.Forms.MessageBox]::Show(
        "FFmpeg is required to create a Final Lap while preserving pitch.`n`n" +
        "FFmpeg was not found on this PC.`n`n" +
        "Download FFmpeg Essentials automatically?`n" +
        "(about 109 MB, first time only)",
        "CTR Music Toolkit",
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question
    )

    if ($answer -ne [System.Windows.Forms.DialogResult]::Yes) {
        return $null
    }

    $toolsDir = Join-Path $PSScriptRoot "tools"
    $zipPath = Join-Path $toolsDir "ffmpeg.zip"
    $extractDir = Join-Path $toolsDir "_ffmpeg_extract"

    try {
        [IO.Directory]::CreateDirectory($toolsDir) | Out-Null

        $status.Text = "Downloading FFmpeg..."
        [System.Windows.Forms.Application]::DoEvents()

        $url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing

        if (Test-Path $extractDir) {
            Remove-Item $extractDir -Recurse -Force
        }

        Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

        $ff = Get-ChildItem $extractDir -Recurse -Filter ffmpeg.exe -File |
            Select-Object -First 1

        if (!$ff) {
            throw "ffmpeg.exe was not found in the ZIP."
        }

        $dest = Join-Path $toolsDir "ffmpeg.exe"
        Copy-Item $ff.FullName $dest -Force

        Remove-Item $extractDir -Recurse -Force
        Remove-Item $zipPath -Force

        $status.Text = "FFmpeg ready."
        return $dest
    }
    catch {
        Show-Error ("Could not set up FFmpeg.`n`n" + $_.Exception.Message)
        return $null
    }
}

function Get-SelectedReferenceRow {
    if ($list.SelectedItems.Count -eq 0) {
        Show-Info "Select a Level ID from the list first."
        return $null
    }

    $row = $list.SelectedItems[0].Tag
    if ($row.ID -eq "" -and !$row.IsCustom) {
        Show-Info "Select a level_XX.ogg file or installed custom track."
        return $null
    }

    return $row
}

function Create-FinalLap {
    if ($pathBox.Text.Trim() -and $pathBox.Text.Trim() -ne $script:RootPath -and !(Apply-RootFromBox)) { return }
    if ([string]::IsNullOrWhiteSpace($script:RootPath)) {
        Pick-Root
        if ([string]::IsNullOrWhiteSpace($script:RootPath)) { return }
    }

    $row = Get-SelectedReferenceRow
    if ($null -eq $row) { return }

    $isCustom = [bool]$row.IsCustom
    $id = if ($isCustom) { $row.Slug } else { [int]$row.ID }
    $normalName = if ($isCustom) { $row.File } else { "level_{0:D2}.ogg" -f $id }
    $finalName = if ($isCustom) {
        [IO.Path]::GetFileNameWithoutExtension($normalName) + "_final.ogg"
    } else { "level_{0:D2}_final.ogg" -f $id }
    $musicDestinations = if ($isCustom) { @($row.ModFolder) } else { @(MusicDirs) }

    $source = $null
    foreach ($d in $musicDestinations) {
        $candidate = Join-Path $d $normalName
        if (Test-Path $candidate -PathType Leaf) {
            $source = $candidate
            break
        }
    }

    if (!$source) {
        Show-Error "This Level ID has no $normalName to convert."
        return
    }

    $ffmpeg = Find-FFmpeg
    if (!$ffmpeg) {
        $ffmpeg = Install-FFmpegForToolkit
        if (!$ffmpeg) { return }
    }

    $temp = Join-Path ([IO.Path]::GetTempPath()) (
        "ctr_final_{0}_{1}.ogg" -f $id, [Guid]::NewGuid().ToString("N")
    )

    try {
        $status.Text = "Creating $finalName at 1.12x..."
        [System.Windows.Forms.Application]::DoEvents()

        # atempo changes tempo while preserving pitch.
        $args = @(
            "-y",
            "-hide_banner",
            "-loglevel", "error",
            "-i", $source,
            "-filter:a", "atempo=1.12",
            "-c:a", "libvorbis",
            "-q:a", "6",
            $temp
        )

        # Native invocation keeps quoted paths intact (including spaces).
        & $ffmpeg @args 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "FFmpeg exited with code $LASTEXITCODE."
        }

        if (!(Test-Path $temp -PathType Leaf) -or ((Get-Item $temp).Length -le 0)) {
            throw "FFmpeg did not produce a valid OGG."
        }

        $ok = 0
        foreach ($d in $musicDestinations) {
            [IO.Directory]::CreateDirectory($d) | Out-Null
            $dest = Join-Path $d $finalName
            [IO.File]::Copy($temp, $dest, $true)

            if ((Test-Path $dest) -and ((Get-Item $dest).Length -gt 0)) {
                $ok++
            }
        }

        if ($ok -ne 1) {
            throw "Could not save $finalName in the game folder."
        }

        $status.Text = "Final Lap created: $finalName - 1.12x, pitch preserved."
        Show-Info (
            "Final Lap created successfully.`n`n" +
            "$finalName`n" +
            "Speed: 1.12x`n" +
            "Pitch: preserved"
        )
    }
    catch {
        Show-Error ("Could not create the Final Lap.`n`n" + $_.Exception.Message)
    }
    finally {
        if (Test-Path $temp) {
            Remove-Item $temp -Force -ErrorAction SilentlyContinue
        }
        Refresh-List
    }
}

function Remove-Selected {
    if ($pathBox.Text.Trim() -and $pathBox.Text.Trim() -ne $script:RootPath -and !(Apply-RootFromBox)) { return }
    if ($list.SelectedItems.Count -eq 0) {
        Show-Info "Select a track from the list."
        return
    }

    $row = $list.SelectedItems[0].Tag

    if (($row.Paths.Count -eq 0) -and !$row.HasFinal) {
        Show-Info "This Level ID has no custom music yet."
        return
    }

    $ans = [System.Windows.Forms.MessageBox]::Show(
        "Remove '$($row.File)'?`n`nThe track will use the original music again.",
        "CTR Music Toolkit",
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question
    )
    if ($ans -ne [System.Windows.Forms.DialogResult]::Yes) { return }

    if ($row.IsCustom) {
        foreach ($name in @("music.ogg","track.ogg","music_final.ogg","track_final.ogg")) {
            $candidate = Join-Path $row.ModFolder $name
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                Remove-Item -LiteralPath $candidate -Force
            }
        }
        Set-CustomTrackAudio $row.ModFolder "none" ""
        Refresh-List
        return
    }
    $musicDir = Join-Path $script:RootPath "assets\MUSIC_CUSTOM"
    $files = @($row.File)
    if ($row.ID -ne "") {
        $files += "level_{0:D2}_final.ogg" -f [int]$row.ID
    }
    foreach ($name in $files) {
        $p = Join-Path $musicDir $name
        if (Test-Path $p -PathType Leaf) { Remove-Item $p -Force }
    }

    Refresh-List
}

function Remove-AllMusic {
    if ($pathBox.Text.Trim() -and $pathBox.Text.Trim() -ne $script:RootPath -and !(Apply-RootFromBox)) { return }
    if ([string]::IsNullOrWhiteSpace($script:RootPath)) { return }

    $ans = [System.Windows.Forms.MessageBox]::Show(
        "Remove ALL custom OGG files?`n`nCTR will use the original music again.",
        "CTR Music Toolkit",
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Warning
    )
    if ($ans -ne [System.Windows.Forms.DialogResult]::Yes) { return }

    foreach ($d in (MusicDirs)) {
        if (Test-Path $d) {
            Get-ChildItem $d -Filter *.ogg -File -ErrorAction SilentlyContinue | Remove-Item -Force
        }
    }

    Refresh-List
}

function Create-Backup {
    if ($pathBox.Text.Trim() -and $pathBox.Text.Trim() -ne $script:RootPath -and !(Apply-RootFromBox)) { return }
    if ([string]::IsNullOrWhiteSpace($script:RootPath)) {
        Pick-Root
        if ([string]::IsNullOrWhiteSpace($script:RootPath)) { return }
    }

    $stamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
    $dest = Join-Path $script:RootPath ("CTR_Music_Backup\" + $stamp)
    [IO.Directory]::CreateDirectory($dest) | Out-Null

    $src = Join-Path $script:RootPath "assets\MUSIC_CUSTOM"
    Ensure-MusicDirs
    Copy-Item $src (Join-Path $dest "MUSIC_CUSTOM") -Recurse -Force

    [IO.File]::WriteAllText(
        (Join-Path $dest "BACKUP_INFO.txt"),
        "CTR Music Toolkit Backup`r`nDate: $(Get-Date)`r`nCTR Native: $script:RootPath",
        [Text.Encoding]::UTF8
    )

    Show-Info "Backup created:`n$dest"
}

function Restore-Backup {
    if ($pathBox.Text.Trim() -and $pathBox.Text.Trim() -ne $script:RootPath -and !(Apply-RootFromBox)) { return }
    if ([string]::IsNullOrWhiteSpace($script:RootPath)) {
        Pick-Root
        if ([string]::IsNullOrWhiteSpace($script:RootPath)) { return }
    }

    $backupRoot = Join-Path $script:RootPath "CTR_Music_Backup"
    if (!(Test-Path $backupRoot)) {
        Show-Info "No backups were found in this folder."
        return
    }

    $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
    $dlg.Description = "Select the backup to restore"
    $dlg.SelectedPath = $backupRoot

    if ($dlg.ShowDialog($form) -ne [System.Windows.Forms.DialogResult]::OK) { return }

    $b = $dlg.SelectedPath
    $src = Join-Path $b "MUSIC_CUSTOM"
    if (!(Test-Path $src -PathType Container)) {
        Show-Error "The selected backup has no MUSIC_CUSTOM folder."
        return
    }
    $dest = Join-Path $script:RootPath "assets\MUSIC_CUSTOM"
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    [IO.Directory]::CreateDirectory((Split-Path $dest -Parent)) | Out-Null
    Copy-Item $src $dest -Recurse -Force

    Refresh-List
    Show-Info "Backup restored."
}

function Open-MusicFolder {
    if ($pathBox.Text.Trim() -and $pathBox.Text.Trim() -ne $script:RootPath -and !(Apply-RootFromBox)) { return }
    if ([string]::IsNullOrWhiteSpace($script:RootPath)) {
        Pick-Root
        if ([string]::IsNullOrWhiteSpace($script:RootPath)) { return }
    }

    Ensure-MusicDirs
    Start-Process explorer.exe (Join-Path $script:RootPath "assets\MUSIC_CUSTOM")
}

# ---------- UI ----------
$form = New-Object System.Windows.Forms.Form
$form.Text = "Crash Forge OGG Toolkit"
$form.StartPosition = "CenterScreen"
$form.MinimumSize = New-Object System.Drawing.Size(920,600)
$form.Size = New-Object System.Drawing.Size(1180,760)
# Native Windows form: start on the monitor occupied by the launcher,
# not WinForms CenterScreen (which otherwise chooses the primary display).
$workarea = $env:CFR_EDITOR_WORKAREA
if ($workarea -match '^(-?\d+),(-?\d+),(-?\d+),(-?\d+)$') {
    try {
        $areaLeft = [int]$Matches[1]
        $areaTop = [int]$Matches[2]
        $areaRight = [int]$Matches[3]
        $areaBottom = [int]$Matches[4]
        if (($areaRight -gt $areaLeft) -and ($areaBottom -gt $areaTop) -and
            ($areaRight - $areaLeft -le 16384) -and
            ($areaBottom - $areaTop -le 16384)) {
            $w = [Math]::Min(1180,$areaRight-$areaLeft)
            $h = [Math]::Min(760,$areaBottom-$areaTop)
            $form.StartPosition = [System.Windows.Forms.FormStartPosition]::Manual
            $form.Size = New-Object System.Drawing.Size($w,$h)
            $form.Location = New-Object System.Drawing.Point(
                ($areaLeft+[int][Math]::Floor(($areaRight-$areaLeft-$w)/2)),
                ($areaTop+[int][Math]::Floor(($areaBottom-$areaTop-$h)/2))
            )
        }
    } catch {}
}
$form.BackColor = $C_BG
$form.ForeColor = $C_TEXT
$form.Font = New-Object System.Drawing.Font("Bahnschrift",9)
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
$form.ShowInTaskbar = $true
$form.ShowIcon = $true
$form.KeyPreview = $true
# Separate OGG Toolkit from Windows PowerShell taskbar grouping.
try {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class CrashForgeOggIdentity {
    [DllImport("shell32.dll", CharSet=CharSet.Unicode)]
    public static extern int SetCurrentProcessExplicitAppUserModelID(string appID);
}
'@ -ErrorAction Stop
    [void][CrashForgeOggIdentity]::SetCurrentProcessExplicitAppUserModelID(
        "CrashForge.Racing.OGGToolkit"
    )
} catch {}


# For the bundled toolkit these resources are extracted beside this script
# by the launcher EXE. No user-specific C: drive paths are necessary.
$forgeAssets = Join-Path $PSScriptRoot "forge_assets"
$forgeBackgroundPath = Join-Path $forgeAssets "Fondo.png"
$forgeIconPath = Join-Path $forgeAssets "icons\cfr_icon.ico"
$forgeLogoPath = Join-Path $forgeAssets "icons\cfr_icon.png"

if (Test-Path $forgeBackgroundPath) {
    try {
        $script:ForgeBackgroundImage = [System.Drawing.Image]::FromFile($forgeBackgroundPath)
        $form.BackgroundImage = $script:ForgeBackgroundImage
        $form.BackgroundImageLayout = [System.Windows.Forms.ImageLayout]::Stretch
    } catch {}
}

if (Test-Path $forgeIconPath) {
    try {
        $form.Icon = New-Object System.Drawing.Icon($forgeIconPath)
        $form.ShowIcon = $true
    } catch {}
}

function New-ForgeButton([string]$text, [int]$width, [string]$kind = "normal") {
    $b = New-Object System.Windows.Forms.Button
    $b.Text = $text
    $b.Size = New-Object System.Drawing.Size($width,36)
    $b.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $b.FlatAppearance.BorderSize = 1
    $b.FlatAppearance.BorderColor = $C_BORDER
    $b.BackColor = $C_PANEL2
    $b.ForeColor = $C_TEXT
    $b.Font = New-Object System.Drawing.Font("Bahnschrift SemiBold",9)
    $b.Cursor = [System.Windows.Forms.Cursors]::Hand
    $b.Margin = New-Object System.Windows.Forms.Padding(0,0,9,0)
    $b.Tag = $kind

    if ($kind -eq "accent") {
        $b.BackColor = [System.Drawing.Color]::FromArgb(55,23,7)
        $b.FlatAppearance.BorderColor = $C_ACCENT
    }
    elseif ($kind -eq "danger") {
        $b.BackColor = [System.Drawing.Color]::FromArgb(40,16,15)
        $b.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(125,50,42)
    }

    $b.Add_MouseEnter({
        if ($this.Tag -eq "accent") {
            $this.BackColor = [System.Drawing.Color]::FromArgb(82,32,7)
            $this.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(255,156,70)
        }
        elseif ($this.Tag -eq "danger") {
            $this.BackColor = [System.Drawing.Color]::FromArgb(78,28,24)
            $this.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(192,70,58)
        }
        else {
            $this.BackColor = [System.Drawing.Color]::FromArgb(31,36,43)
            $this.FlatAppearance.BorderColor = $C_ACCENT
        }
    })
    $b.Add_MouseLeave({
        if ($this.Tag -eq "accent") {
            $this.BackColor = [System.Drawing.Color]::FromArgb(55,23,7)
            $this.FlatAppearance.BorderColor = $C_ACCENT
        }
        elseif ($this.Tag -eq "danger") {
            $this.BackColor = [System.Drawing.Color]::FromArgb(40,16,15)
            $this.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(125,50,42)
        }
        else {
            $this.BackColor = $C_PANEL2
            $this.FlatAppearance.BorderColor = $C_BORDER
        }
    })
    return $b
}

# Floating Forge header over the workshop artwork.
$header = New-Object System.Windows.Forms.Panel
$header.Dock = "Top"
$header.Height = 82
$header.BackColor = [System.Drawing.Color]::Transparent

$brandShade = New-Object System.Windows.Forms.Panel
$brandShade.Location = New-Object System.Drawing.Point(0,0)
$brandShade.Size = New-Object System.Drawing.Size(470,82)
$brandShade.BackColor = [System.Drawing.Color]::FromArgb(8,9,11)

$logo = New-Object System.Windows.Forms.PictureBox
$logo.Location = New-Object System.Drawing.Point(18,11)
$logo.Size = New-Object System.Drawing.Size(58,58)
$logo.SizeMode = [System.Windows.Forms.PictureBoxSizeMode]::Zoom
$logo.BackColor = [System.Drawing.Color]::Transparent
if (Test-Path $forgeLogoPath) {
    try { $logo.Image = [System.Drawing.Image]::FromFile($forgeLogoPath) } catch {}
}
if (($null -eq $logo.Image) -and ($null -ne $form.Icon)) {
    try { $logo.Image = $form.Icon.ToBitmap() } catch {}
}

$title = New-Object System.Windows.Forms.Label
$title.Text = "CRASH FORGE / OGG TOOLKIT"
$title.Font = New-Object System.Drawing.Font("Bahnschrift SemiBold",18)
$title.ForeColor = $C_TEXT
$title.BackColor = [System.Drawing.Color]::Transparent
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(88,17)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = "MUSIC PORTING  /  WINDOWS TOOL"
$subtitle.Font = New-Object System.Drawing.Font("Bahnschrift SemiBold",8)
$subtitle.ForeColor = $C_ACCENT
$subtitle.BackColor = [System.Drawing.Color]::Transparent
$subtitle.AutoSize = $true
$subtitle.Location = New-Object System.Drawing.Point(90,51)

$toolVersion = New-Object System.Windows.Forms.Label
$toolVersion.Text = "TOOLKIT v1.0.9"
$toolVersion.Font = New-Object System.Drawing.Font("Bahnschrift",8)
$toolVersion.ForeColor = $C_MUTED
$toolVersion.BackColor = [System.Drawing.Color]::Transparent
$toolVersion.AutoSize = $true
$toolVersion.Anchor = "Top,Right"
$toolVersion.Location = New-Object System.Drawing.Point(930,29)

$btnMini = New-Object System.Windows.Forms.Label
$btnMini.Text = "—"
$btnMini.TextAlign = "MiddleCenter"
$btnMini.Size = New-Object System.Drawing.Size(38,34)
$btnMini.Anchor = "Top,Right"
$btnMini.Location = New-Object System.Drawing.Point(1046,18)
$btnMini.BackColor = [System.Drawing.Color]::Transparent
$btnMini.ForeColor = $C_TEXT
$btnMini.Font = New-Object System.Drawing.Font("Segoe UI",12)
$btnMini.Cursor = [System.Windows.Forms.Cursors]::Hand

$btnMax = New-Object System.Windows.Forms.Label
$btnMax.Text = "□"
$btnMax.TextAlign = "MiddleCenter"
$btnMax.Size = New-Object System.Drawing.Size(38,34)
$btnMax.Anchor = "Top,Right"
$btnMax.Location = New-Object System.Drawing.Point(1084,18)
$btnMax.BackColor = [System.Drawing.Color]::Transparent
$btnMax.ForeColor = $C_TEXT
$btnMax.Font = New-Object System.Drawing.Font("Segoe UI",11)
$btnMax.Cursor = [System.Windows.Forms.Cursors]::Hand

$btnClose = New-Object System.Windows.Forms.Label
$btnClose.Text = "×"
$btnClose.TextAlign = "MiddleCenter"
$btnClose.Size = New-Object System.Drawing.Size(38,34)
$btnClose.Anchor = "Top,Right"
$btnClose.Location = New-Object System.Drawing.Point(1122,18)
$btnClose.BackColor = [System.Drawing.Color]::Transparent
$btnClose.ForeColor = $C_TEXT
$btnClose.Font = New-Object System.Drawing.Font("Segoe UI",18)
$btnClose.Cursor = [System.Windows.Forms.Cursors]::Hand

$btnMini.Add_MouseEnter({ $this.ForeColor = [System.Drawing.Color]::White })
$btnMini.Add_MouseLeave({ $this.ForeColor = $C_TEXT })
$btnMax.Add_MouseEnter({ $this.ForeColor = [System.Drawing.Color]::White })
$btnMax.Add_MouseLeave({ $this.ForeColor = $C_TEXT })
$btnClose.Add_MouseEnter({ $this.ForeColor = [System.Drawing.Color]::FromArgb(255,105,88) })
$btnClose.Add_MouseLeave({ $this.ForeColor = $C_TEXT })

$btnMini.Add_Click({ $form.WindowState = [System.Windows.Forms.FormWindowState]::Minimized })
$btnMax.Add_Click({
    if ($form.WindowState -eq [System.Windows.Forms.FormWindowState]::Maximized) {
        $form.WindowState = [System.Windows.Forms.FormWindowState]::Normal
        $btnMax.Text = "□"
    } else {
        $form.WindowState = [System.Windows.Forms.FormWindowState]::Maximized
        $btnMax.Text = "❐"
    }
})
$btnClose.Add_Click({ $form.Close() })

$script:DraggingForgeWindow = $false
$script:DragOffset = New-Object System.Drawing.Point(0,0)
$header.Add_MouseDown({
    if ($_.Button -eq [System.Windows.Forms.MouseButtons]::Left -and
        $form.WindowState -eq [System.Windows.Forms.FormWindowState]::Normal) {
        $script:DraggingForgeWindow = $true
        $script:DragOffset = New-Object System.Drawing.Point($_.X, $_.Y)
    }
})
$header.Add_MouseMove({
    if ($script:DraggingForgeWindow) {
        $screen = $header.PointToScreen($_.Location)
        $form.Location = New-Object System.Drawing.Point(
            ($screen.X - $script:DragOffset.X),
            ($screen.Y - $script:DragOffset.Y)
        )
    }
})
$header.Add_MouseUp({ $script:DraggingForgeWindow = $false })
$header.Add_DoubleClick({ $btnMax.PerformClick() })

$brandShade.Controls.AddRange(@($logo,$title,$subtitle))
$logo.BringToFront()
$header.Controls.Add($brandShade)
$header.Controls.AddRange(@($toolVersion,$btnMini,$btnMax,$btnClose))

# Game path card.
$pathWrap = New-Object System.Windows.Forms.Panel
$pathWrap.Dock = "Top"
$pathWrap.Height = 104
$pathWrap.BackColor = [System.Drawing.Color]::Transparent
$pathWrap.Padding = New-Object System.Windows.Forms.Padding(18,7,18,9)

$pathCard = New-Object System.Windows.Forms.Panel
$pathCard.Dock = "Fill"
$pathCard.BackColor = $C_PANEL
$pathCard.Padding = New-Object System.Windows.Forms.Padding(15,10,15,10)

$pathAccent = New-Object System.Windows.Forms.Panel
$pathAccent.Dock = "Left"
$pathAccent.Width = 3
$pathAccent.BackColor = $C_ACCENT

$pathLabel = New-Object System.Windows.Forms.Label
$pathLabel.Text = "GAME INSTALLATION"
$pathLabel.ForeColor = $C_MUTED
$pathLabel.BackColor = [System.Drawing.Color]::Transparent
$pathLabel.Font = New-Object System.Drawing.Font("Bahnschrift SemiBold",8)
$pathLabel.AutoSize = $true
$pathLabel.Location = New-Object System.Drawing.Point(18,10)

$pathBox = New-Object System.Windows.Forms.TextBox
$pathBox.ReadOnly = $false
$pathBox.BackColor = $C_INPUT
$pathBox.ForeColor = $C_TEXT
$pathBox.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$pathBox.Font = New-Object System.Drawing.Font("Bahnschrift",9)
$pathBox.Location = New-Object System.Drawing.Point(18,38)
$pathBox.Height = 30
$pathBox.Anchor = "Top,Left,Right"
$pathBox.Width = 900

$btnRoot = New-ForgeButton "BROWSE" 104 "accent"
$btnRoot.Location = New-Object System.Drawing.Point(936,34)
$btnRoot.Anchor = "Top,Right"

$btnAbout = New-ForgeButton "ABOUT" 86 "normal"
$btnAbout.Location = New-Object System.Drawing.Point(1048,34)
$btnAbout.Anchor = "Top,Right"

$pathCard.Controls.AddRange(@($pathAccent,$pathLabel,$pathBox,$btnRoot,$btnAbout))
$pathWrap.Controls.Add($pathCard)

# Action strip with Forge buttons.
$actionsWrap = New-Object System.Windows.Forms.Panel
$actionsWrap.Dock = "Top"
$actionsWrap.Height = 76
$actionsWrap.BackColor = [System.Drawing.Color]::Transparent
$actionsWrap.Padding = New-Object System.Windows.Forms.Padding(18,5,18,9)

$actions = New-Object System.Windows.Forms.FlowLayoutPanel
$actions.Dock = "Fill"
$actions.Padding = New-Object System.Windows.Forms.Padding(12,11,12,8)
$actions.BackColor = $C_PANEL
$actions.WrapContents = $false
$actions.AutoScroll = $true

$btnAdd = New-ForgeButton "ADD / REPLACE" 150 "accent"
$btnFinal = New-ForgeButton "CREATE FINAL LAP" 145 "normal"
$btnRemove = New-ForgeButton "REMOVE SELECTED" 150 "normal"
$btnRemoveAll = New-ForgeButton "REMOVE ALL" 105 "danger"
$btnBackup = New-ForgeButton "BACKUP" 88 "normal"
$btnRestore = New-ForgeButton "RESTORE" 96 "normal"
$btnFolder = New-ForgeButton "OPEN FOLDER" 112 "normal"
$btnRefresh = New-ForgeButton "REFRESH MODS" 120 "normal"

$actions.Controls.AddRange(@($btnAdd,$btnFinal,$btnRemove,$btnRemoveAll,$btnBackup,$btnRestore,$btnFolder,$btnRefresh))
$actionsWrap.Controls.Add($actions)

# Main track browser.
$main = New-Object System.Windows.Forms.Panel
$main.Dock = "Fill"
$main.Padding = New-Object System.Windows.Forms.Padding(18,0,18,12)
$main.BackColor = [System.Drawing.Color]::Transparent

$listCard = New-Object System.Windows.Forms.Panel
$listCard.Dock = "Fill"
$listCard.BackColor = $C_PANEL
$listCard.Padding = New-Object System.Windows.Forms.Padding(1,1,1,1)

$list = New-Object System.Windows.Forms.ListView
$list.Dock = "Fill"
$list.View = [System.Windows.Forms.View]::Details
$list.FullRowSelect = $true
$list.GridLines = $false
$list.HideSelection = $false
$list.BackColor = $C_PANEL
$list.ForeColor = $C_TEXT
$list.BorderStyle = [System.Windows.Forms.BorderStyle]::None
$list.Font = New-Object System.Drawing.Font("Bahnschrift",10)
$list.HeaderStyle = [System.Windows.Forms.ColumnHeaderStyle]::Nonclickable
$list.OwnerDraw = $true

[void]$list.Columns.Add("ID",70)
[void]$list.Columns.Add("TRACK",250)
[void]$list.Columns.Add("FILE",330)
[void]$list.Columns.Add("STATUS",110)

$list.Add_DrawColumnHeader({
    $e = $_
    $e.Graphics.FillRectangle((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(18,21,26))), $e.Bounds)
    $e.Graphics.DrawLine((New-Object System.Drawing.Pen($C_BORDER)), $e.Bounds.Left, $e.Bounds.Bottom - 1, $e.Bounds.Right, $e.Bounds.Bottom - 1)
    $brush = New-Object System.Drawing.SolidBrush($C_MUTED)
    $font = New-Object System.Drawing.Font("Bahnschrift SemiBold",8)
    $e.Graphics.DrawString($e.Header.Text, $font, $brush, ($e.Bounds.Left + 9), ($e.Bounds.Top + 7))
    $brush.Dispose()
    $font.Dispose()
})
$list.Add_DrawItem({ $_.DrawDefault = $true })
$list.Add_DrawSubItem({ $_.DrawDefault = $true })

$listCard.Controls.Add($list)
$main.Controls.Add($listCard)

# Bottom status rail.
$statusWrap = New-Object System.Windows.Forms.Panel
$statusWrap.Dock = "Bottom"
$statusWrap.Height = 44
$statusWrap.BackColor = [System.Drawing.Color]::Transparent
$statusWrap.Padding = New-Object System.Windows.Forms.Padding(18,0,18,10)

$statusCard = New-Object System.Windows.Forms.Panel
$statusCard.Dock = "Fill"
$statusCard.BackColor = $C_PANEL

$statusAccent = New-Object System.Windows.Forms.Panel
$statusAccent.Dock = "Left"
$statusAccent.Width = 3
$statusAccent.BackColor = $C_ACCENT

$status = New-Object System.Windows.Forms.Label
$status.Dock = "Fill"
$status.Padding = New-Object System.Windows.Forms.Padding(12,7,10,0)
$status.BackColor = $C_PANEL
$status.ForeColor = $C_MUTED
$status.Font = New-Object System.Drawing.Font("Bahnschrift",8)
$status.Text = "Select or enter the folder containing ctr_native.exe to begin."

$statusCard.Controls.Add($status)
$statusCard.Controls.Add($statusAccent)
$statusWrap.Controls.Add($statusCard)

$form.Controls.Add($main)
$form.Controls.Add($statusWrap)
$form.Controls.Add($actionsWrap)
$form.Controls.Add($pathWrap)
$form.Controls.Add($header)

# Responsive placement.
$form.Add_Resize({
    $pathBox.Width = [Math]::Max(350, $pathCard.ClientSize.Width - 260)
    $btnRoot.Left = $pathCard.ClientSize.Width - 218
    $btnAbout.Left = $pathCard.ClientSize.Width - 104

    $toolVersion.Left = [Math]::Max(640, $header.ClientSize.Width - 250)
    $btnMini.Left = $header.ClientSize.Width - 126
    $btnMax.Left = $header.ClientSize.Width - 88
    $btnClose.Left = $header.ClientSize.Width - 50

    $available = [Math]::Max(520, $list.ClientSize.Width - 10)
    $list.Columns[0].Width = 70
    $list.Columns[3].Width = 110
    $remaining = $available - 180
    $list.Columns[1].Width = [Math]::Max(190, [int]($remaining * 0.38))
    $list.Columns[2].Width = [Math]::Max(250, $remaining - $list.Columns[1].Width)
})

# Initial responsive positioning.
$form.PerformLayout()
$pathBox.Width = [Math]::Max(350, $pathCard.ClientSize.Width - 260)
$btnRoot.Left = $pathCard.ClientSize.Width - 218
$btnAbout.Left = $pathCard.ClientSize.Width - 104

# Game directory is read-only here; only Launcher > Settings can change it.
$pathBox.ReadOnly = $true
$btnRoot.Text = "SETTINGS"
$btnRoot.Add_Click({
    Show-Info "The game installation folder is managed by Crash Forge Launcher > Settings."
})
$btnAbout.Add_Click({
    Show-Info "Crash Forge OGG Toolkit v1.0.9`n`nManage custom OGG tracks for Crash Forge: Racing. The game folder is shared automatically with Crash Forge Launcher Settings.`n`nThe 65 provided names are numbered in their original order from 0 to 64. OGG filenames use these decimal numbers.`n`nTrack ID findings: Discord @carisa15demon"
})
$btnAdd.Add_Click({ Add-Music })
$btnFinal.Add_Click({ Create-FinalLap })
$btnRemove.Add_Click({ Remove-Selected })
$btnRemoveAll.Add_Click({ Remove-AllMusic })
$btnBackup.Add_Click({ Create-Backup })
$btnRestore.Add_Click({ Restore-Backup })
$btnFolder.Add_Click({ Open-MusicFolder })
$btnRefresh.Add_Click({ Refresh-List })
$list.Add_DoubleClick({
    if ($list.SelectedItems.Count -gt 0) {
        $row = $list.SelectedItems[0].Tag
        if ($row.IsCustom) {
            Add-MusicForCustom $row
        } elseif ($row.ID -ne "") {
            Add-MusicForId ([int]$row.ID)
        }
    }
})

if ($env:CFR_GAME_PATH -and (Test-CtrRoot $env:CFR_GAME_PATH)) {
    [void](Set-Root $env:CFR_GAME_PATH)
}

# Capture only the REAL program UI for the launcher NEWS preview. This does
# not draw or generate artistic imagery; it screenshots our actual WinForms UI.
# No window is shown or moved on the user's desktop.
if ($env:CFR_OGG_CAPTURE) {
    $form.CreateControl()
    $form.PerformLayout()
    $dimensions = New-Object System.Drawing.Size(1180,760)
    $bitmap = New-Object System.Drawing.Bitmap($dimensions.Width,$dimensions.Height)
    $form.DrawToBitmap($bitmap,(New-Object System.Drawing.Rectangle(0,0,1180,760)))
    $bitmap.Save($env:CFR_OGG_CAPTURE,[System.Drawing.Imaging.ImageFormat]::Png)
    $bitmap.Dispose()
    $form.Dispose()
    return
}

# Headless smoke against the compiled OGG EXE, no dialogs shown.
if ($env:CFR_OGG_SMOKE -eq "1") {
    $rows = @(Get-TrackRows)
    [PSCustomObject]@{
        GameRoot = [bool]$script:RootPath
        Hangout = [bool](@($rows | Where-Object { $_.ID -eq 99 }).Count -gt 0)
        NativeTrack = [bool](@($rows | Where-Object {
            $_.IsCustom -and $_.Slug -eq "my_custom_track"
        }).Count -gt 0)
        Logo = [bool]($null -ne $logo.Image)
        WindowIcon = [bool]($null -ne $form.Icon)
        TaskbarEnabled = [bool]$form.ShowInTaskbar
    } | ConvertTo-Json -Compress
    $form.Dispose()
    return
}
[void]$form.ShowDialog()
