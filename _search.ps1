Get-ChildItem -Recurse -File | Select-String -Pattern 'parallel_workers','AppConfig' -SimpleMatch | ForEach-Object {
  Write-Output (":: {0}" -f (/bin/bash.Line.Trim()))
}
