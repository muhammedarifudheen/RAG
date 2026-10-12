<#
.SYNOPSIS
  Asks for an Anthropic API key in a small window and saves it to .env in the
  repo folder, where docker compose and run-in-cloud-shell.ps1 read it.

.DESCRIPTION
  Only the ANTHROPIC_API_KEY line of .env is replaced; other lines are kept.
  The key is written to that file and nowhere else.
#>
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$envFile = Join-Path (Split-Path -Parent $PSScriptRoot) ".env"

$form = New-Object System.Windows.Forms.Form
$form.Text = "Atlas - Anthropic API key"
$form.Size = New-Object System.Drawing.Size(560, 230)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.TopMost = $true

$label = New-Object System.Windows.Forms.Label
$label.Location = New-Object System.Drawing.Point(16, 14)
$label.Size = New-Object System.Drawing.Size(520, 58)
$label.Text = "Paste your Anthropic API key below (Ctrl+V) and click Save.`r`n" +
    "Create one at console.anthropic.com > API keys. It starts with sk-ant-`r`n" +
    "It is saved only to: $envFile"
$form.Controls.Add($label)

$box = New-Object System.Windows.Forms.TextBox
$box.Location = New-Object System.Drawing.Point(16, 80)
$box.Size = New-Object System.Drawing.Size(510, 24)
$form.Controls.Add($box)

$status = New-Object System.Windows.Forms.Label
$status.Location = New-Object System.Drawing.Point(16, 112)
$status.Size = New-Object System.Drawing.Size(510, 22)
$status.ForeColor = [System.Drawing.Color]::Firebrick
$form.Controls.Add($status)

$save = New-Object System.Windows.Forms.Button
$save.Text = "Save"
$save.Location = New-Object System.Drawing.Point(340, 145)
$save.Size = New-Object System.Drawing.Size(90, 30)
$form.AcceptButton = $save
$form.Controls.Add($save)

$cancel = New-Object System.Windows.Forms.Button
$cancel.Text = "Cancel"
$cancel.Location = New-Object System.Drawing.Point(436, 145)
$cancel.Size = New-Object System.Drawing.Size(90, 30)
$cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
$form.CancelButton = $cancel
$form.Controls.Add($cancel)

$save.Add_Click({
    $key = $box.Text.Trim().Trim('"').Trim("'")
    if ($key -notmatch "^sk-ant-\S{20,}$") {
        $status.Text = "That does not look like an Anthropic key. It should start with sk-ant- and have no spaces."
        return
    }
    $kept = @()
    if (Test-Path -LiteralPath $envFile) {
        $kept = @(Get-Content -LiteralPath $envFile | Where-Object { $_ -notmatch "^\s*ANTHROPIC_API_KEY\s*=" })
    }
    $text = (($kept + "ANTHROPIC_API_KEY=$key") -join "`n") + "`n"
    [IO.File]::WriteAllText($envFile, $text, (New-Object Text.UTF8Encoding $false))
    $form.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $form.Close()
})

$form.Add_Shown({ $form.Activate(); $box.Focus() })
[void]$form.ShowDialog()
