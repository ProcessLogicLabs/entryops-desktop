# User Workflow

This flowchart shows the end-to-end user journey for processing customs documentation.

```mermaid
flowchart TD
    subgraph Setup["Initial Setup (One-time)"]
        A[Install EntryOps] --> B[Launch Application]
        B --> C[Open Settings Dialog]
        C --> C1[General: Set Theme, MID List]
        C1 --> C2[PDF Processing: Set Folders]
        C2 --> C3[Templates: Configure Shared Folder]
        C3 --> D[Create Folder Profiles]
        D --> E[Import Parts via Parts Import Tab]
        E --> F[Create Mapping Profiles]
    end

    subgraph Daily["Daily Workflow"]
        G[Receive Invoice] --> G1[Select Folder Profile]
        G1 --> H{File Format?}
        H -->|PDF| I[Use PDF Processing Tab]
        H -->|CSV/Excel| J[Use Invoice Processing Tab]

        I --> K[Auto-Match Template]
        K --> L[Extract + Enrich Data]
        L --> L1{Missing Parts?}
        L1 -->|Yes| L2[Add Missing Parts Dialog]
        L2 --> L3[Direct Export to XLSX]
        L1 -->|No| L3
        L3 --> L4[Review Validation Summary in Log]

        J --> N[Select File from Input Files List]
        N --> O[Select/Create Mapping]
        O --> P[Enter Invoice Total]
        P --> Q[Select MID from Dropdown]
        Q --> R[Click Process Invoice]
    end

    subgraph Review["Review & Edit"]
        R --> S[View Preview Table]
        S --> S1[Review Color-Coded Material Types]
        S1 --> T{Data Correct?}
        T -->|No| U[Edit Values in Table]
        U --> V[Reprocess if Needed]
        V --> S
        T -->|Yes| W[Verify Total Matches]
    end

    subgraph Export["Export & Archive"]
        W --> X[Click Export Worksheet]
        X --> Y[Choose Split Options]
        Y --> Z[Generate CBP Worksheet]
        Z --> AA[File Saved to Output Folder]
        AA --> AB[Source Moved to Processed]
        AB --> AC[Done]
    end

    subgraph Maintenance["Periodic Maintenance"]
        AD[Parts View: Search/Edit Records] --> AE[Query Builder for Complex Searches]
        AE --> AF[Parts Import: Bulk Import New Parts]
        AF --> AG[Settings > Database: Backup]
        AG --> AH[Settings > Templates: Sync Shared Templates]
    end

    style A fill:#4CAF50,color:#fff
    style AC fill:#4CAF50,color:#fff
    style T fill:#FFC107,color:#000
    style C fill:#9C27B0,color:#fff
```

## Detailed User Steps

### Initial Setup

1. **Install Application**
   - Run EntryOps_Setup.exe installer
   - Or use standalone EntryOps.exe

2. **Configure Settings** (Settings > Settings)
   - **General**: Choose theme (Light/Dark), configure MID list
   - **PDF Processing**: Set default OCRMill input/output folders and output profile
   - **Templates**: Configure shared templates network folder
   - **Database**: View database location, configure backups
   - **Updates**: Enable/disable automatic update checks

3. **Create Folder Profiles**
   - Invoice Processing tab → Folder Profile dropdown → Manage (gear icon)
   - Create profiles for different clients/projects
   - Each profile stores input and output folder paths

4. **Import Parts Data**
   - Parts Import tab (dedicated import interface)
   - Load CSV file → Preview data → Map columns
   - Select import mode (Insert/Update/Upsert)
   - Click Import Parts

5. **Create Mapping Profiles**
   - Process first invoice from each supplier
   - Create mapping for that invoice format
   - Save profile for future use

### Daily Invoice Processing

```mermaid
sequenceDiagram
    participant User
    participant EntryOps
    participant Database
    participant FileSystem

    User->>EntryOps: Select Folder Profile
    EntryOps->>FileSystem: Load Input Files List
    User->>EntryOps: Select Invoice File
    EntryOps->>EntryOps: Parse CSV/Excel
    User->>EntryOps: Select Mapping Profile
    EntryOps->>EntryOps: Apply Column Mapping
    User->>EntryOps: Enter Invoice Total
    User->>EntryOps: Select MID
    User->>EntryOps: Click Process Invoice
    EntryOps->>Database: Lookup Part Numbers
    Database-->>EntryOps: Return Part Data
    EntryOps->>EntryOps: Calculate Tariffs & Materials
    EntryOps->>EntryOps: Distribute Values
    EntryOps-->>User: Display Color-Coded Preview
    User->>EntryOps: Verify & Edit
    User->>EntryOps: Click Export Worksheet
    EntryOps->>FileSystem: Save Excel to Output Folder
    EntryOps->>FileSystem: Move Source to Processed
    EntryOps-->>User: Confirm Complete
```

### Quick Reference

| Task | Location | Steps |
|------|----------|-------|
| Process CSV/Excel Invoice | Invoice Processing tab | Select Folder Profile → Select File → Map → Process → Export |
| Process PDF Invoice (OCRMill) | PDF Processing tab | Drop PDFs → Auto-match template → Direct XLSX export → Review log summary |
| Add Missing Parts during OCRMill | Automatic dialog | Add/skip parts → pipeline re-enriches and exports |
| Update Section 232 pct from PDF | Automatic confirmation dialog | Review calculated values → Confirm to write to parts_master |
| Manage Folder Profiles | Invoice Processing tab | Click gear icon next to Folder Profile dropdown |
| Add New Part | Parts View tab | Right-click → Add Row |
| Edit Part | Parts View tab | Double-click cell |
| Search Parts | Parts View tab | Use search box or Query Builder button |
| Import Parts (Bulk) | Parts Import tab | Load CSV → Map Columns → Import |
| Configure MID List | Settings > Settings > General | Edit MID List section |
| Change Theme | Settings > Settings > General | Select Light/Dark/System |
| Configure Shared Templates | Settings > Settings > Templates | Set shared folder, click Sync |
| Backup Database | Settings > Settings > Database | Click Backup Now |
| View Logs | Log View menu | View Log |

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+O | Open invoice file |
| Ctrl+S | Save/Export |
| Ctrl+P | Process invoice |
| Ctrl+F | Search parts |
| Ctrl+R | Refresh/Reprocess |
| F5 | Refresh file lists |

### Troubleshooting Common Issues

| Issue | Solution |
|-------|----------|
| Part not found | Add via Parts View or via the Add Missing Parts dialog during OCRMill processing |
| Values don't match | Edit directly in preview table |
| Wrong HTS code | Update in Parts View tab |
| Missing MID | Add to MID list in Settings > General |
| Export fails | Check output folder permissions; network paths get 3 automatic retries |
| Scanned PDF warning | OCRMill cannot process image-only PDFs; text-based PDFs required |
| Shared templates not showing | Check Settings > Templates folder path |
| Folder profile not applying | Click Sync or reselect the profile |
| Section 232 pct not updating | Re-run OCRMill with the PDF containing embedded 232 forms and confirm the dialog |
