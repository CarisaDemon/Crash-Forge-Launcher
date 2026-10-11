"""Crash Forge: Racing Mod Packager GUI (Windows, no console)."""
from __future__ import annotations

import ctypes
import queue
import threading
import os
from pathlib import Path
import sys
import zipfile
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from companion_tools.mod_packager import mod_packager_core as engine
from companion_tools.mod_packager.packager_auth import check_account
from forge_editor_geometry import initial_geometry
from forge_editor_config import selected_game_directory, selected_game_explanation
from forge_model_preview import (
    PreviewPane, TextureGallery, model_sources_from_folder,
    texture_sources_from_folder,
)

DARK="#0B0D10"
PANEL="#11161C"
FIELD="#171D24"
LINE="#39434D"
ORANGE="#FF781A"
FOREGROUND="#EFF2F1"
MUTED="#AAB0B7"
WEB_URL="https://carisademon.github.io/Crash-Forge-Racing/forge-hub/studio.html"


def bundle(path):
    base=Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parents[2]))
    return base/Path(path)

class Packager(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Crash Forge: Racing - Mod Packager")
        self.configure(bg=DARK)
        self.minsize(770,570)
        self.geometry(initial_geometry(1110,790) or "1110x790")
        try:
            ico=bundle("assets/icons/cfr_icon.ico")
            if ico.is_file():self.iconbitmap(str(ico))
            if os.name=="nt":
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "CrashForge.Racing.ModPackager")
        except (OSError,RuntimeError):pass
        self.kind=tk.StringVar(value="Character")
        self.title_var=tk.StringVar()
        self.author=tk.StringVar()
        self.version=tk.StringVar(value="1.0")
        self.path_label=tk.StringVar(value="No mod files selected.")
        self.status=tk.StringVar(value="Choose a category and your native mod assets.")
        self.folder=None
        self.selected=[]
        self.preview_files=[]
        self.preview_selected=tk.StringVar()
        self.bg_image=None
        self._ui()
        self._status_bindings()
    def _ui(self):
        head=tk.Canvas(self,height=140,bg="#16100C",highlightthickness=0)
        head.pack(fill="x")
        image=bundle("assets/Fondo.png")
        if image.is_file():
            try:
                from PIL import Image,ImageTk,ImageEnhance
                picture=Image.open(image).convert("RGB")
                picture=ImageEnhance.Brightness(picture).enhance(.35)
                picture=picture.resize((1080,180),Image.Resampling.LANCZOS)
                self.bg_image=ImageTk.PhotoImage(picture)
                head.create_image(0,0,anchor="nw",image=self.bg_image)
            except (ImportError,OSError):pass
        head.create_rectangle(0,0,8,140,fill=ORANGE,outline="")
        head.create_text(28,28,text="CRASH FORGE  //  EDITOR",anchor="w",
                         fill=FOREGROUND,font=("Bahnschrift SemiBold",20))
        head.create_text(29,70,text="MOD PACKAGER",anchor="w",
                         fill=ORANGE,font=("Bahnschrift SemiBold",25))
        head.create_text(29,116,text="BUILD • VALIDATE • EXPORT • SHARE",anchor="w",
                         fill="#BAC1C8",font=("Bahnschrift",10))
        content=tk.Frame(self,bg=DARK)
        content.pack(expand=True,fill="both",padx=18,pady=(12,6))
        body=tk.Frame(content,bg=DARK)
        body.pack(side="left",fill="both",expand=True,padx=(0,10))
        body.columnconfigure(1,weight=1)
        showcase=tk.Frame(content,bg=PANEL,
                          highlightbackground=LINE,highlightthickness=1)
        showcase.pack(side="right",fill="both",expand=True,padx=(5,0))
        tk.Label(showcase,text="LIVE ASSET PREVIEW",bg=PANEL,fg=ORANGE,
                 font=("Bahnschrift SemiBold",11),anchor="w").pack(
                     fill="x",padx=11,pady=(10,5))
        self.viewer=PreviewPane(showcase,width=410,height=285)
        self.viewer.pack(fill="x",padx=9)
        chooser=tk.Frame(showcase,bg=PANEL)
        chooser.pack(fill="x",padx=9,pady=(7,1))
        tk.Label(chooser,text="Model",fg=MUTED,bg=PANEL).pack(side="left",padx=(0,5))
        self.model_choices=ttk.Combobox(
            chooser,textvariable=self.preview_selected,state="readonly")
        self.model_choices.pack(side="left",fill="x",expand=True)
        self.model_choices.bind("<<ComboboxSelected>>",
                                lambda e:self._show_selected_model())
        self.gallery=TextureGallery(
            showcase,editable=False,on_preview=self.viewer.set_variant)
        self.gallery.pack(fill="x",padx=7,pady=(8,2))
        tk.Label(showcase,
            text="OBJ: textured preview  |  LEV: geometry + vertex colors. "
                 "VRM mapping needs runtime decoding.",
            bg=PANEL,fg=MUTED,wraplength=430,justify="left",
            font=("Bahnschrift",8)).pack(fill="x",padx=11,pady=(5,7))
        def label(text,row):
            tk.Label(body,text=text,bg=DARK,fg=ORANGE,anchor="w",
                     font=("Bahnschrift SemiBold",10)).grid(
                         row=row,column=0,sticky="w",pady=7,padx=(0,16))
        def field(var,row):
            e=tk.Entry(body,textvariable=var,bg=FIELD,fg=FOREGROUND,
                       insertbackground=ORANGE,relief="flat",
                       font=("Bahnschrift",11),highlightthickness=1,
                       highlightbackground=LINE,highlightcolor=ORANGE)
            e.grid(row=row,column=1,sticky="ew",pady=5,ipady=7)
            return e
        label("MOD NAME",0);field(self.title_var,0)
        label("CATEGORY",1)
        combo=ttk.Combobox(body,textvariable=self.kind,
                           values=list(engine.CATEGORIES),state="readonly")
        combo.grid(row=1,column=1,sticky="ew",pady=5,ipady=6)
        label("AUTHOR",2);field(self.author,2)
        label("VERSION",3);field(self.version,3)
        label("DESCRIPTION",4)
        self.description=tk.Text(body,height=3,bg=FIELD,fg=FOREGROUND,
                                 insertbackground=ORANGE,relief="flat",
                                 font=("Bahnschrift",10),wrap="word",
                                 highlightthickness=1,highlightbackground=LINE)
        self.description.grid(row=4,column=1,sticky="ew",pady=6)
        label("SOURCE FILES",5)
        select=tk.Frame(body,bg=DARK)
        select.grid(row=5,column=1,sticky="ew")
        self._button(select,"CHOOSE FOLDER",self.select_folder).pack(side="left",padx=(0,8),pady=4)
        self._button(select,"SELECT FILES",self.select_files,secondary=True).pack(side="left",pady=4)
        tk.Label(body,textvariable=self.path_label,bg=DARK,fg=MUTED,
                 font=("Bahnschrift",9),wraplength=690,anchor="w",
                 justify="left").grid(row=6,column=1,sticky="ew",pady=(2,7))
        tk.Label(body,text="Native OBJ models or LEV+VRM tracks only. "
                 "No ISO, saves, scripts, executables or private game files.",
                 bg=DARK,fg="#D6A677",font=("Bahnschrift",9),
                 justify="left",wraplength=440).grid(row=7,column=0,
                     columnspan=2,sticky="w",pady=6)
        selected=selected_game_directory(source_file=__file__)
        self.game_reference=tk.StringVar(
            value=selected_game_explanation(selected))
        tk.Label(body,text="GAME PATH FROM LAUNCHER SETTINGS",
                 fg=ORANGE,bg=DARK,anchor="w",
                 font=("Bahnschrift SemiBold",8)).grid(
                     row=8,column=0,columnspan=2,sticky="w",pady=(9,1))
        tk.Label(body,textvariable=self.game_reference,
                 fg=MUTED,bg=DARK,justify="left",anchor="w",
                 wraplength=440,font=("Bahnschrift",8)).grid(
                     row=9,column=0,columnspan=2,sticky="w")
        footer=tk.Frame(self,bg="#10141A")
        footer.pack(fill="x",side="bottom")
        tk.Label(footer,textvariable=self.status,fg="#D9B592",
                 bg="#10141A",anchor="w",justify="left",wraplength=900,
                 font=("Bahnschrift",10)).pack(fill="x",padx=22,pady=(12,4))
        row=tk.Frame(footer,bg="#10141A")
        row.pack(fill="x",padx=22,pady=(5,16))
        self._button(row,"EXPORT ZIP",self.export).pack(side="left")
        self._button(row,"OPEN FORGE HUB",lambda:webbrowser.open(WEB_URL),
                     secondary=True).pack(side="left",padx=12)
        tk.Label(row,text="Web ID assigned when published",bg="#10141A",
                 fg=MUTED,font=("Bahnschrift",9)).pack(side="right")
    def _status_bindings(self):
        def validate(*args):
            if self.folder or self.selected:
                self.status.set("Ready to validate and export the selected assets.")
        self.kind.trace_add("write",validate)
        self.kind.trace_add("write",lambda *_:self._refresh_preview())
    def _button(self,parent,text,callback,secondary=False):
        return tk.Button(parent,text=text,command=callback,relief="flat",
                         borderwidth=1,highlightthickness=0,
                         bg="#242B34" if secondary else "#5C240B",
                         activebackground="#A04710",
                         fg=FOREGROUND,activeforeground="white",
                         font=("Bahnschrift SemiBold",10),
                         cursor="hand2",padx=18,pady=9)
    def select_folder(self):
        selected=filedialog.askdirectory(parent=self,
                  title="Select the native mod's folder")
        if selected:
            self.folder=Path(selected)
            self.selected=[]
            self.path_label.set(str(self.folder)+" (includes supported subfolders)")
            self.status.set("Folder selected. Export will validate its contents.")
            self._refresh_preview()
    def select_files(self):
        chosen=filedialog.askopenfilenames(parent=self,title="Select mod assets")
        if chosen:
            self.selected=list(chosen)
            self.folder=None
            self.path_label.set(str(len(self.selected))+" files selected: "+
                 ", ".join(Path(p).name for p in self.selected[:5]))
            self.status.set("Files selected. Export will validate their contents.")
            self._refresh_preview()

    def _refresh_preview(self):
        """Any mod category can preview its source mesh and detected textures."""
        category=self.kind.get()
        selected=self.selected
        self.preview_files=(
            model_sources_from_folder(self.folder,category=category)
            if self.folder else [
                Path(path) for path in selected
                if Path(path).suffix.lower()==(".lev" if category=="Track" else ".obj")
            ])
        self.model_choices.configure(
            values=[path.name for path in self.preview_files])
        if self.preview_files:
            self.preview_selected.set(self.preview_files[0].name)
            self._show_selected_model()
        else:
            self.preview_selected.set("")
            self.viewer.scene=None
            self.viewer.image.configure(image="",text="Choose a model to preview.")
            self.viewer.detail.set("No previewable model chosen yet.")
        paths=(texture_sources_from_folder(self.folder) if self.folder
               else [Path(file) for file in selected
                    if Path(file).suffix.lower() in (
                        ".png",".bmp",".jpg",".jpeg",".tga")])
        self.gallery.load(paths)

    def _show_selected_model(self):
        if not self.preview_files:return
        name=self.preview_selected.get()
        source=next((p for p in self.preview_files if p.name==name),
                    self.preview_files[0])
        self.viewer.load(source,category=self.kind.get())

    def export(self):
        title=self.title_var.get().strip()
        name=engine.folder_name(title or "untitled_mod")+".zip"
        target=filedialog.asksaveasfilename(
            parent=self,title="Export Crash Forge native mod",
            defaultextension=".zip",initialfile=name,
            filetypes=[("ZIP archive","*.zip")])
        if not target:return
        try:
            result=engine.build_mod_zip(
                title=title,kind=self.kind.get(),
                author=self.author.get(),version=self.version.get(),
                description=self.description.get("1.0","end-1c"),
                source_folder=self.folder,selected_files=self.selected,output=target)
            self.status.set("ZIP READY • "+str(result["file_count"])+
                " assets • "+f'{result["size"]/1048576:.2f} MiB'+
                " • SHA-256 "+result["sha256"][:16]+"...")
            messagebox.showinfo("Crash Forge: Mod Packager",
                "Validated ZIP saved:\n"+result["path"]+
                "\n\nOpen Forge Hub Creator Studio to submit it for review."+
                "\nForge Hub will assign the permanent web ID.",parent=self)
        except (engine.PackageError,OSError,ValueError,zipfile.BadZipFile) as e:
            self.status.set("PACKAGING BLOCKED: "+str(e))
            messagebox.showerror("Mod ZIP not created",str(e),parent=self)


class AccountGate(tk.Tk):
    """No exporter widgets or mod files are accessible before online auth."""
    def __init__(self):
        super().__init__()
        self.approved = False
        self._result = queue.Queue()
        self._busy = False
        self.title("Crash Forge: Racing - Forge Hub Account Required")
        self.configure(bg=DARK)
        self.resizable(False, False)
        self.geometry(initial_geometry(580,270) or "580x270")
        head = tk.Frame(self, bg="#181F27")
        head.pack(fill="x")
        tk.Label(head, text="MOD PACKAGER  /  FORGE HUB",
                 bg="#181F27", fg=ORANGE,
                 font=("Bahnschrift SemiBold",16)).pack(anchor="w",padx=25,pady=14)
        self.message = tk.StringVar(
            value="Verifying your saved Forge Hub account securely...")
        tk.Label(self, textvariable=self.message, bg=DARK, fg=FOREGROUND,
                 wraplength=510, justify="left",font=("Bahnschrift",11),
                 anchor="w").pack(fill="x",padx=25,pady=(25,12))
        tools=tk.Frame(self,bg=DARK)
        tools.pack(fill="x",padx=25)
        self.retry=tk.Button(tools,text="RETRY",command=self.verify,
                             state="disabled",bg="#75330F",fg=FOREGROUND,
                             activebackground=ORANGE,relief="flat",
                             font=("Bahnschrift SemiBold",10),padx=18,pady=9)
        self.retry.pack(side="left",padx=(0,10))
        tk.Button(tools,text="CLOSE",command=self.destroy,
                  bg="#252D35",fg=FOREGROUND,
                  relief="flat",padx=16,pady=9).pack(side="left")
        self.after(50,self.verify)
        self.after(120,self._poll)

    def verify(self):
        if self._busy:return
        self._busy=True
        self.retry.configure(state="disabled")
        self.message.set("Verifying your Forge Hub session...")
        def worker():
            self._result.put(check_account())
        threading.Thread(target=worker,daemon=True,
                         name="ForgeModPackagerAuthentication").start()

    def _poll(self):
        try:
            accepted,status=self._result.get_nowait()
        except queue.Empty:
            self.after(120,self._poll)
            return
        self._busy=False
        if accepted:
            self.approved=True
            self.destroy()
            return
        self.message.set(status)
        self.retry.configure(state="normal")
        self.after(120,self._poll)


def main():
    gate=AccountGate()
    gate.mainloop()
    if gate.approved:
        Packager().mainloop()

def _self_test():
    """No GUI, assets or installed Python needed for packaged smoke."""
    import tempfile
    from companion_tools.mod_packager import mod_packager_core as core
    with tempfile.TemporaryDirectory() as work:
        path=Path(work)
        (path/"example.obj").write_bytes(b"o TEST\\nv 0 0 0\\n")
        target=path.parent/("cfr_packager_smoke_"+path.name+".zip")
        try:
            result=core.build_mod_zip(
                title="Smoke Racer",kind="Character",version="1.0",
                selected_files=[path/"example.obj"],output=target)
            if not target.is_file() or result["size"]<=0:
                raise RuntimeError("Mod Packager smoke ZIP failed")
        finally:
            target.unlink(missing_ok=True)
    return 0

if __name__=="__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(_self_test())
    main()
