import QrScanner from './js/qr-scanner.min.js';
QrScanner.WORKER_PATH = './js/qr-scanner-worker.min.js';

const state = {
    camera: {
        scanner: null,
        play_state: false
    },
    controls: {
        play_state: false, /* camera on? */
    },
    file: {
        name: '',
        chunks: 0,
        chunks_recvd: 0,
        bytes: 0,
        data: [],
        live: false
    },
    last_packet: null
};

function receivedQR(data) {
    if (data == state.last_packet) {
        return;
    }
    //console.log('receivedQR', data);
    state.last_packet = data;

    /*
     * format of packet
     * magic,version,filename,total number of chunks,chunk number,base64 encoded chunk
     * e.g. L1FB,1,foo.txt,3,1,TWFuIGlzIGRpc3Rpbm
     */
    const f = state.file;
    const comps = data.split(',');
    if (comps[0] !== 'L1FB' && comps[1] !== '1') {
       console.log('not Lifi broadcast packet');
       return;
    }
    const chunks = parseInt(comps[3], 10),
       idx = parseInt(comps[4], 10);

    if (f.live) {
       /* existing download */
       if (comps[2] !== f.name || chunks !== f.chunks) {
           console.log(`not the same file ${f.name}/${f.chunks}: ${comps[2]}/${comps[3]}`);
           return;
       }
    } else {
       if (isNaN(chunks)) {
           console.log('invalid chunks', comps[3]);
           return;
       }
       f.name = comps[2];
       f.chunks = chunks;
       f.live = true;
    }
    if (isNaN(idx)) {
       console.log('invalid idx', comps[4]);
       return;
    }
    if (f.data[idx] !== undefined) {
        console.log('we already have chunk', idx);
        return;
    }

    let decoded = '';
    try {
        decoded = atob(comps[5]);
    } catch (e) {
        console.error(e);
        return;
    }

    const bblob = b64Blob(decoded);
    f.data[idx] = bblob;
    f.chunks_recvd += 1;
    f.bytes += bblob.size;
    render();
}

function b64Blob(str) {
    const ab = new ArrayBuffer(str.length),
        bytes = new Uint8Array(ab);

    for (var i = 0; i < str.length; i++) {
        bytes[i] = str.charCodeAt(i);
    }
    return new Blob([ab], {type: 'application/octet-stream'});
}

function receivedError(e) {
    //console.log('receivedError', e);
}

function rinit() {
    state.camera.scanner = new QrScanner($('#vid_player')[0], receivedQR, receivedError);
}

function render() {
    updateStatus();
    updateButtons();
    updateCamera();
}

function updateStatus() {
    const modestr = 'Lifi Receiver',
        f = state.file,
        connstr = state.file.live ? 'receiving': 'waiting',
        recvstr = state.file.live ? `${f.name} ${f.chunks_recvd}/${f.chunks} chunks, ${f.bytes} bytes`: '';
    $('.status').text(`${modestr} ${connstr} ${recvstr}`);
}

function updateButtons() {
    $('.play_state').text(state.controls.play_state ? 'Pause' : 'Scan');
    if (state.file.live && state.file.chunks === state.file.chunks_recvd) {
        $('.download_file').css('background-color', 'green');
    } else {
        $('.download_file').css('background-color', '');
    }
}

function updateCamera() {
    const enabled = state.controls.play_state,
        cam = state.camera;

    if (cam.scanner && cam.play_state !== enabled) {
        if (enabled) {
            console.log('starting scanner');
            cam.scanner.start();
        } else {
            cam.scanner.stop();
            console.log('stopping scanner');
        }
        cam.play_state = enabled;
    }
}

function resetAll() {
    console.log('reset all');
    if (state.camera.scanner) {
        console.log('reset scanner');
        state.camera.scanner.stop();
    }
    state.controls.play_state = state.camera.play_state = false;
    const f = state.file;
    f.name = '';
    f.chunks = f.chunks_recvd = f.bytes = 0;
    f.data = [];
    f.live = false;
    state.last_packet = null;
}

function saveFile() {
    const f = state.file;
    if (f.chunks && f.chunks === f.chunks_recvd) {
        saveAs(new Blob(state.file.data, {type: 'application/octet-stream'}), f.name);
    } else {
        console.log('nothing to save yet');
    }
}

$('.play_state').click(x => {
    state.controls.play_state = !state.controls.play_state;
    render();
});

$('.reset_all').click(x => {
    resetAll();
    render();
});

$('.download_file').click(x => {
    saveFile();
});

rinit();
