"""Forge Profiles UI, inside Mod Manager; local-first and explicit cloud actions."""
import queue
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog
import forge_profiles as profiles

BG="#0C0F14"; PANEL="#171C23"; ORANGE="#FF6A00"; WHITE="#F5F0E9"; MUTED="#9CA5B0"

def show(app):
    previous=getattr(app,"_forge_profiles_window",None)
    if previous is not None and previous.winfo_exists():
        previous.lift();return
    window=tk.Toplevel(app)
    app._forge_profiles_window=window
    window.title("Forge Profiles - Local & Cloud")
    window.configure(bg=BG)
    window.geometry("680x550")
    window.minsize(535,420)
    window.transient(app)
    tk.Frame(window,bg=ORANGE,height=5).pack(fill="x")
    tk.Label(window,text="FORGE PROFILES",bg=BG,fg=WHITE,
             font=("Bahnschrift SemiBold",19)).pack(anchor="w",padx=22,pady=(15,3))
    tk.Label(window,text="Save mod switches locally. Upload or download cloud copies only when you choose.",
             bg=BG,fg=MUTED,font=("Bahnschrift",9)).pack(anchor="w",padx=22)
    header=tk.Frame(window,bg=BG)
    header.pack(fill="x",padx=20,pady=(12,5))
    tk.Label(header,text="LOCAL PROFILES",bg=BG,fg=ORANGE,
             font=("Bahnschrift SemiBold",10)).pack(side="left")
    tk.Label(header,text="CLOUD COPIES",bg=BG,fg=ORANGE,
             font=("Bahnschrift SemiBold",10)).pack(side="right",padx=(10,0))
    grid=tk.Frame(window,bg=BG)
    grid.pack(fill="both",expand=True,padx=20,pady=(0,7))
    left=tk.Frame(grid,bg=PANEL)
    right=tk.Frame(grid,bg=PANEL)
    left.pack(side="left",fill="both",expand=True,padx=(0,6))
    right.pack(side="left",fill="both",expand=True,padx=(6,0))
    local=tk.Listbox(left,bg=PANEL,fg=WHITE,selectbackground="#743613",
                     selectforeground=WHITE,activestyle="none",borderwidth=0,
                     highlightthickness=0,font=("Bahnschrift",10),
                     exportselection=False)
    cloud=tk.Listbox(right,bg=PANEL,fg=WHITE,selectbackground="#743613",
                     selectforeground=WHITE,activestyle="none",borderwidth=0,
                     highlightthickness=0,font=("Bahnschrift",10),
                     exportselection=False)
    local.pack(fill="both",expand=True,padx=8,pady=8)
    cloud.pack(fill="both",expand=True,padx=8,pady=8)
    local_data=[];cloud_data=[]
    jobs=queue.Queue()
    status=tk.Label(window,text="Offline profiles work without a Forge Hub account.",
                    bg=BG,fg=MUTED,font=("Bahnschrift",9),anchor="w",
                    wraplength=610)
    status.pack(fill="x",padx=20,pady=(5,8))

    def inform(msg):status.configure(text=str(msg)[:260])
    def refresh_local():
        nonlocal local_data
        try:
            local_data=profiles.load(app.game_install_path)["profiles"]
        except (profiles.ProfileError,OSError) as exc:
            inform(exc);local_data=[]
        local.delete(0,tk.END)
        for entry in local_data:
            local.insert(tk.END,f'{entry["name"]}  ({len(entry["mods"])} mods)')
    def selected(values,control):
        sel=control.curselection()
        return values[sel[0]] if sel else None
    def create():
        name=simpledialog.askstring("New Forge Profile","Choose a profile name:",
                                   parent=window)
        if name is None:return
        try:
            result=profiles.snapshot(app.game_install_path,name)
            refresh_local()
            inform(f'Saved "{result["name"]}" locally. No mod state was changed.')
        except (profiles.ProfileError,OSError) as exc:inform(exc)
    def apply():
        entry=selected(local_data,local)
        if entry is None:inform("Select a local profile first.");return
        if getattr(app,"game_update_busy",False) or getattr(app,"mod_download_busy",False):
            inform("Wait for the current game or mod installation.");return
        try:
            changes,missing=profiles.plan_apply(app.game_install_path,entry)
            if not changes and not missing:
                inform("Already matches this profile.");return
            summary=f'{len(changes)} mod switch(es), {len(missing)} missing mod(s).'
            if not messagebox.askyesno("Apply Forge Profile",
                    summary+"\n\nOnly installed mods in the snapshot are changed."
                    "\nMissing mods are not installed; extra mods are not changed."
                    "\nRestart the game afterward.",parent=window):return
            updated,missing=profiles.apply(app.game_install_path,entry)
            inform(f"Applied {updated} mod switch(es). Missing {len(missing)}. Restart game.")
            if hasattr(app,"_render_hub_cards"):
                app._render_hub_cards()
        except (profiles.ProfileError,OSError) as exc:
            messagebox.showerror("Forge Profiles",str(exc),parent=window)
    def erase_selected():
        remote=selected(cloud_data,cloud)
        if remote is not None:
            if not messagebox.askyesno(
                "Delete CLOUD profile",
                f'Delete "{remote["name"]}" permanently from your Forge Hub cloud?'
                "\n\nYour local copy, installed mods and saves will NOT be deleted."
                "\nThis cannot be undone.",
                parent=window, icon="warning"):
                return
            async_call("Delete cloud profile",
                       lambda:profiles.cloud_delete(app.account_client,remote))
            return
        entry=selected(local_data,local)
        if entry is None:
            inform("Select a LOCAL or CLOUD profile first.")
            return
        if messagebox.askyesno("Delete LOCAL profile",
                f'Delete local "{entry["name"]}"?'
                "\nYour cloud copies and installed mods stay untouched.",
                parent=window):
            try:
                profiles.delete(app.game_install_path,entry["id"])
                refresh_local()
                update_delete_button()
                inform("Local copy deleted. Cloud copies were not modified.")
            except (profiles.ProfileError,OSError) as exc:
                inform(exc)
    def async_call(action,func):
        if not app.account_client.signed_in:
            inform("Sign in to your Forge Hub account to use Cloud Sync.");return
        inform(action+"...")
        def worker():
            try: jobs.put((action,True,func()))
            except Exception as error:jobs.put((action,False,str(error)))
        threading.Thread(target=worker,daemon=True,name="ForgeProfilesCloud").start()
    def fetch():
        async_call("Fetch cloud profiles",lambda:profiles.cloud_list(app.account_client))
    def upload():
        entry=selected(local_data,local)
        if entry is None:inform("Select a local profile to upload.");return
        if not messagebox.askyesno("Upload Forge Profile",
                f'Upload "{entry["name"]}" to your private Forge Hub account?\n'
                "This only uploads mod identifiers and enabled states.",
                parent=window):return
        async_call("Upload cloud copy",lambda:profiles.cloud_upload_new(app.account_client,entry))
    def download():
        entry=selected(cloud_data,cloud)
        if entry is None:inform("Fetch and select a cloud profile first.");return
        try:
            profiles.cloud_import(app.game_install_path,entry)
            refresh_local()
            inform("Downloaded cloud profile. Installed mods were not modified.")
        except (profiles.ProfileError,OSError) as exc:inform(exc)
    def make_button(parent,label,action,accent=False):
        return tk.Button(parent,text=label,command=action,cursor="hand2",relief="flat",
                         bg="#663009" if accent else "#252B33",fg=WHITE,
                         activebackground=ORANGE,activeforeground="white",
                         font=("Bahnschrift SemiBold",8),padx=8,pady=7)
    control=tk.Frame(window,bg=BG)
    control.pack(fill="x",padx=20,pady=(1,10))
    def update_delete_button():
        remote=selected(cloud_data,cloud)
        local_row=selected(local_data,local)
        delete_button.configure(
            text="DELETE CLOUD" if remote is not None else "DELETE LOCAL",
            state="normal" if (remote or local_row) else "disabled",
            bg="#6B251A" if remote else "#252B33")

    def on_local_select(_event=None):
        if local.curselection():
            cloud.selection_clear(0,tk.END)
        update_delete_button()

    def on_cloud_select(_event=None):
        if cloud.curselection():
            local.selection_clear(0,tk.END)
        update_delete_button()

    local.bind("<<ListboxSelect>>",on_local_select,add="+")
    cloud.bind("<<ListboxSelect>>",on_cloud_select,add="+")
    for name,action,acc in [("SAVE CURRENT",create,True),("APPLY",apply,False),
                             ("DELETE",erase_selected,False),
                             ("UPLOAD",upload,False),("FETCH CLOUD",fetch,False),
                             ("DOWNLOAD",download,False)]:
        button=make_button(control,
                           "DELETE LOCAL" if name=="DELETE" else name,action,acc)
        button.pack(side="left",padx=(0,5))
        if name=="DELETE":
            delete_button=button
    update_delete_button()
    def poll():
        nonlocal cloud_data
        if not window.winfo_exists():return
        try:
            while True:
                action,success,result=jobs.get_nowait()
                if not success:
                    inform(f"{action}: {result}");continue
                if action=="Fetch cloud profiles":
                    cloud_data=result
                    cloud.delete(0,tk.END)
                    for entry in cloud_data:
                        cloud.insert(tk.END,f'{entry["name"]} ({len(entry["mods"])} mods)')
                    update_delete_button()
                    inform(f"Found {len(result)} private cloud profile(s).")
                elif action=="Delete cloud profile":
                    cloud_data=[p for p in cloud_data if p["id"]!=result]
                    cloud.delete(0,tk.END)
                    for entry in cloud_data:
                        cloud.insert(tk.END,f'{entry["name"]} ({len(entry["mods"])} mods)')
                    update_delete_button()
                    inform("Cloud copy deleted. Local profiles and installed mods were NOT touched.")
                else:
                    inform("Cloud copy uploaded. Use FETCH CLOUD to refresh.")
        except queue.Empty:pass
        window.after(125,poll)
    refresh_local()
    poll()
