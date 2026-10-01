 ## Usage

 ### Interactive mode

 Same as before:

```
python merge_aliases.py
```

 ### Merge one alias

```
python merge_aliases.py --alias "0Kablaaa" --into 1
```

 It will show:

```
Processing 1 merge(s)...

  0Kablaaa: 0Kablaaa -> Kablaaa
  Continue? [y/N]:
```

 ### Merge several aliases into the same player

```
python merge_aliases.py \
    --alias "0Kablaaa" \
    --alias "Kablaaa_2" \
    --alias "OldKablaaa" \
    --into 1
```

 ### Skip confirmations

 Useful for scripts:

```
python merge_aliases.py \
    --alias "0Kablaaa" \
    --alias "Kablaaa_2" \
    --into 1 \
    --yes
```

 ### Use a merge CSV

 Create `merges.csv`:

```
alias,player_id
0Kablaaa,1
Kablaaa_2,1
OldKablaaa,1
OldSaiel,2
Saiel123,2
```

 Then:

```
python merge_aliases.py --file merges.csv
```

 Or completely unattended:

```
python merge_aliases.py --file merges.csv --yes
```

 ### One useful safety property

 The script **doesn't delete the historical records** when merging. It only changes:

```
player_aliases.player_id
```

 So a historical record that originally said:

```
0Kablaaa
```

 continues to say:

```
name_used = 0Kablaaa
```

 but queries through the canonical player now correctly identify it as:

```
canonical_name = Kablaaa
```

 This means you can safely run the merger repeatedly; already-correct aliases are detected and reported as `SKIP` rather than causing duplicate data.
